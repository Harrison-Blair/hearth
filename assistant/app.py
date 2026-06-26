"""Daemon entrypoint.

Boots, loads config, resolves audio devices, speaks a greeting, then runs the
full voice pipeline: wake word -> record -> transcribe -> route -> LLM -> speak.
"""

from __future__ import annotations

import asyncio
import logging

from assistant.audio.devices import DeviceSelection, select_devices
from assistant.audio.earcon import tone
from assistant.audio.recorder import VadRecorder
from assistant.audio.sounddevice_io import SoundDeviceIn, SoundDeviceOut
from assistant.core.arbiter import AudioArbiter
from assistant.core.config import Config
from assistant.core.logging import setup_logging
from assistant.core.pipeline import VoicePipeline
from assistant.llm.ollama_provider import OllamaProvider
from assistant.nlu.classifier_router import ClassifierRouter
from assistant.nlu.keyphrase_router import KeyphraseRouter
from assistant.scheduling.scheduler import ReminderScheduler
from assistant.search.base import SearchProvider
from assistant.search.ddgs_provider import DdgsSearch
from assistant.search.tavily import TavilySearch
from assistant.skills.base import SkillRegistry
from assistant.skills.clock import ClockSkill
from assistant.skills.general import GeneralSkill
from assistant.skills.reminder import ReminderSkill
from assistant.skills.web_search import WebSearchSkill
from assistant.storage.reminders import ReminderStore
from assistant.stt.faster_whisper_stt import FasterWhisperSTT
from assistant.tts.piper_tts import PiperTTS
from assistant.wake.openwakeword_detector import OpenWakeWordDetector

log = logging.getLogger("assistant")

GREETING = "Hello, I'm your personal assistant. I'm listening."

# Candidate intents the LLM classifier picks from (label -> description). Ordered;
# the keys are also the valid set. Mirrors the keyphrase registrations below and the
# skills' declared intents — this is routing wiring, so it lives here, not in config.
INTENTS = {
    "time": "the current clock time",
    "date": "today's date or the day of week",
    "timer": "start a countdown timer for a relative duration",
    "reminder": "create a reminder for a future time",
    "list_reminders": "read back the user's pending reminders",
    "manage_reminders": "cancel, reschedule, or rename an existing reminder",
    "web_search": "search the live web for current or up-to-date information",
    "general": "any other question or request answered from general knowledge",
}


def main() -> None:
    config = Config()
    setup_logging(config.logging.level)

    log.info("Personal assistant booting (v%s)", __import__("assistant").__version__)
    log.info(
        "Config: wake=%r models=%s | stt=%s | llm=%s@%s | tts=%s",
        config.wake.phrase,
        config.wake.model_refs(),
        config.stt.model,
        config.llm.model,
        config.llm.host,
        config.tts.model_path or config.tts.voice,
    )

    try:
        devices = select_devices(config.audio)
    except Exception as exc:  # noqa: BLE001 - surface device problems clearly at boot
        log.error("Audio device selection failed: %s", exc)
        return

    try:
        asyncio.run(_run(config, devices))
    except KeyboardInterrupt:
        log.info("Shutting down.")


async def _run(config: Config, devices: DeviceSelection) -> None:
    if not config.tts.model_path:
        log.error("No TTS model configured (tts.model_path); cannot speak. Aborting.")
        return

    # Voice out.
    tts = PiperTTS(config.tts.model_path)
    out = SoundDeviceOut(
        devices.output.index, tts.sample_rate, volume=config.audio.output_volume
    )

    # LLM + routing + skills.
    llm = OllamaProvider(
        config.llm.model,
        config.llm.host,
        config.llm.timeout,
        config.llm.health_timeout,
    )
    if not await llm.health():
        log.warning(
            "Ollama not ready (host=%s, model=%s); answers will fail until it's up. "
            "Run `ollama serve` and `ollama pull %s`.",
            config.llm.host,
            config.llm.model,
            config.llm.model,
        )
    store = ReminderStore(config.storage.db_path)
    # The keyphrase matcher is the offline fallback; the LLM classifier is primary.
    keyphrases = KeyphraseRouter(default_intent="general")
    keyphrases.add("time", "what time", "the time")
    keyphrases.add("date", "what day", "what's the date", "the date", "today's date")
    keyphrases.add("timer", "set a timer", "set timer", "timer for")
    keyphrases.add("reminder", "remind me", "set a reminder")
    keyphrases.add("manage_reminders", "cancel", "clear", "delete", "forget", "remove",
                   "change my", "change the", "update my", "reschedule", "move my", "rename")
    keyphrases.add("list_reminders", "my reminders", "any reminders", "have reminders")
    keyphrases.add("web_search", "search the web", "search for", "look up", "look it up",
                   "google", "what's the latest", "latest on")
    router = ClassifierRouter(llm, keyphrases, INTENTS)
    # Keyless scraper is the guaranteed path; Tavily is an optional keyed accelerator
    # (live answer box) used only when a key is configured, with ddgs as its fallback.
    search: SearchProvider = DdgsSearch(
        result_count=config.web_search.result_count,
        timeout=config.web_search.timeout,
        region=config.web_search.region,
        timelimit=config.web_search.timelimit,
        max_snippet_chars=config.web_search.max_snippet_chars,
    )
    if config.web_search.api_key:
        search = TavilySearch(
            config.web_search.api_key,
            endpoint=config.web_search.tavily_endpoint,
            timeout=config.web_search.timeout,
            max_snippet_chars=config.web_search.max_snippet_chars,
            fallback=search,
        )
        log.info("Web search: Tavily (keyed) with ddgs fallback")
    else:
        log.info("Web search: ddgs (keyless); set web_search.api_key for live answers")
    registry = SkillRegistry()
    registry.register(ClockSkill())
    registry.register(ReminderSkill(store, llm))
    registry.register(WebSearchSkill(search, llm, count=config.web_search.result_count))
    registry.register(GeneralSkill(llm, config.llm.system_prompt), default=True)

    # Greeting.
    log.info("Speaking greeting: %r", GREETING)
    await out.play(await tts.synthesize(GREETING))

    # Voice in: wake -> record -> transcribe.
    detector = OpenWakeWordDetector(
        config.wake.model_refs(), config.wake.threshold
    )
    stt = FasterWhisperSTT(
        config.stt.model,
        config.stt.compute_type,
        config.stt.language,
        config.stt.beam_size,
    )
    audio_in = SoundDeviceIn(
        devices.input.index,
        sample_rate=config.audio.sample_rate,
        block_size=config.audio.block_size,
        channels=config.audio.channels,
    )
    recorder = VadRecorder(
        sample_rate=config.audio.sample_rate,
        aggressiveness=config.recorder.aggressiveness,
        silence_ms=config.recorder.silence_ms,
        max_ms=config.recorder.max_ms,
        start_timeout_ms=config.recorder.start_timeout_ms,
    )

    arbiter = AudioArbiter()
    pipeline = VoicePipeline(
        audio_in,
        detector,
        recorder,
        stt,
        router,
        registry,
        tts,
        out,
        arbiter,
        preroll_frames=config.recorder.preroll_frames,
        sample_rate=config.audio.sample_rate,
        no_speech_earcon=tone(tts.sample_rate),
    )
    scheduler = ReminderScheduler(
        store, tts, out, arbiter, poll_seconds=config.scheduling.poll_seconds
    )

    # Pipeline (wake -> reply) and scheduler (proactive reminders) share the one
    # event loop, audio output, and arbiter; both run until interrupted.
    try:
        await asyncio.gather(pipeline.run(), scheduler.run())
    finally:
        store.close()


if __name__ == "__main__":
    main()
