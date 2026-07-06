"""Daemon entrypoint.

Boots, loads config, resolves audio devices, plays a startup chime, then runs the
full voice pipeline: wake word -> record -> transcribe -> route -> LLM -> speak.
"""

from __future__ import annotations

import asyncio
import logging
import sys

from assistant.audio.devices import DeviceSelection, select_devices
from assistant.audio.earcon import chime, descending, no_speech
from assistant.audio.recorder import VadRecorder
from assistant.audio.sounddevice_io import SoundDeviceIn, SoundDeviceOut
from assistant.core.arbiter import AudioArbiter
from assistant.core.config import Config, WebSearchConfig
from assistant.core.control import ControlChannel
from assistant.core.logging import setup_logging
from assistant.core.orchestrator import Orchestrator
from assistant.core.pipeline import VoicePipeline
from assistant.core.speech import Speaker
from assistant.core.state import NullStateEmitter, StateEmitter
from assistant.llm.ollama_provider import OllamaProvider
from assistant.nlu.command_router import CommandEntryRouter
from assistant.nlu.keyphrase_router import KeyphraseRouter
from assistant.scheduling.scheduler import ReminderScheduler
from assistant.search.base import SearchProvider
from assistant.search.ddgs_provider import DdgsSearch
from assistant.search.multi import MultiSearch
from assistant.search.wikipedia import WikipediaSearch
from assistant.skills.base import SkillRegistry
from assistant.skills.clock import ClockSkill
from assistant.skills.general import GeneralSkill
from assistant.skills.reminder import ReminderSkill
from assistant.skills.weather import WeatherSkill
from assistant.skills.web_search import WebSearchSkill
from assistant.storage.reminders import ReminderStore
from assistant.stt.faster_whisper_stt import FasterWhisperSTT
from assistant.tts.piper_tts import PiperTTS
from assistant.wake.livekit_detector import LivekitWakeDetector
from assistant.weather.open_meteo import OpenMeteoWeather

log = logging.getLogger("assistant")


def _build_search(cfg: WebSearchConfig) -> SearchProvider:
    """Construct the configured provider fan-out. Unknown names are skipped with
    a warning; an empty list falls back to Wikipedia so search never disappears."""
    factories = {
        "wikipedia": lambda: WikipediaSearch(
            language=cfg.language,
            result_count=cfg.result_count,
            timeout=cfg.timeout,
            max_snippet_chars=cfg.max_snippet_chars,
        ),
        "ddgs": lambda: DdgsSearch(
            region=cfg.region,
            timeout=cfg.timeout,
            max_snippet_chars=cfg.max_snippet_chars,
        ),
    }
    providers: list[SearchProvider] = []
    names: list[str] = []
    for name in cfg.providers:
        factory = factories.get(name)
        if factory is None:
            log.warning("Unknown web search provider %r; skipping", name)
            continue
        providers.append(factory())
        names.append(name)
    if not providers:
        log.warning("No usable web search providers configured; falling back to wikipedia")
        providers, names = [factories["wikipedia"]()], ["wikipedia"]
    log.info(
        "Web search: %s (agentic, max_rounds=%d)", "+".join(names), cfg.max_rounds
    )
    if len(providers) == 1:
        return providers[0]
    return MultiSearch(providers, max_results=cfg.max_results)


def main() -> None:
    config = Config()
    setup_logging(config.logging.level)

    log.info("Personal assistant booting (v%s)", __import__("assistant").__version__)
    log.info(
        "Config: wake=%r models=%s | stt=%s | llm=%s@%s | tts=%s",
        ", ".join(config.wake.phrases()),
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
    tts = PiperTTS(config.tts.model_path, config.tts.length_scale)
    out = SoundDeviceOut(
        devices.output.index, tts.sample_rate, volume=config.audio.output_volume
    )

    # LLM + routing + skills.
    llm = OllamaProvider(
        config.llm.model,
        config.llm.host,
        config.llm.timeout,
        config.llm.health_timeout,
        config.llm.num_ctx,
        config.llm.think,
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
    # The keyphrase matcher is the orchestrator's LLM-free fast path for cheap,
    # frequent commands; anything it doesn't confidently match enters the tool loop.
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
    keyphrases.add("weather", "weather", "forecast", "temperature",
                   "will it rain", "how hot", "how cold")
    search = _build_search(config.web_search)
    weather = OpenMeteoWeather(
        forecast_endpoint=config.weather.forecast_endpoint,
        geocoding_endpoint=config.weather.geocoding_endpoint,
        temperature_unit=config.weather.temperature_unit,
        wind_speed_unit=config.weather.wind_speed_unit,
        precipitation_unit=config.weather.precipitation_unit,
        timezone=config.weather.timezone,
        forecast_days=config.weather.forecast_days,
        timeout=config.weather.timeout,
    )
    registry = SkillRegistry()
    registry.register(ClockSkill())
    registry.register(ReminderSkill(store, llm))
    registry.register(WebSearchSkill(
        search,
        llm,
        count=config.web_search.result_count,
        max_rounds=config.web_search.max_rounds,
        speaker=Speaker(tts, out),
        progress_updates=config.web_search.progress_updates,
    ))
    registry.register(WeatherSkill(
        weather,
        llm,
        home_lat=config.weather.latitude,
        home_lon=config.weather.longitude,
        home_name=config.weather.location_name,
    ))
    registry.register(GeneralSkill(llm, config.llm.system_prompt), default=True)
    # Fast path: explicit "tool X" invocation, then keyphrase match. Both LLM-free;
    # a miss returns the default intent, which drops the turn into the tool loop.
    fast_path = CommandEntryRouter(
        config.nlu.command_keyphrase,
        registry,
        next_router=keyphrases,
        aliases=config.nlu.command_aliases,
    )
    orchestrator = Orchestrator(
        llm,
        registry,
        fast_path,
        tool_mode=config.agent.tool_mode,
        max_tool_rounds=config.agent.max_tool_rounds,
        fast_path_enabled=config.agent.fast_path,
        system_prompt=config.llm.system_prompt,
        turn_timeout_s=config.agent.turn_timeout_s,
    )

    # Startup chime.
    log.info("Playing startup chime")
    await out.play(chime(tts.sample_rate))

    # Voice in: wake -> record -> transcribe.
    detector = LivekitWakeDetector(
        config.wake.model_refs(),
        config.wake.threshold,
        score_interval=config.wake.score_interval,
        trigger_frames=config.wake.trigger_frames,
    )
    stt = FasterWhisperSTT(
        config.stt.model,
        config.stt.compute_type,
        config.stt.language,
        config.stt.beam_size,
        vad_filter=config.stt.vad_filter,
        condition_on_previous_text=config.stt.condition_on_previous_text,
        initial_prompt=config.stt.initial_prompt,
        device=config.stt.device,
        cpu_threads=config.stt.cpu_threads,
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
    # Spoken wake acknowledgements, synthesized once and cached as PCM so they play
    # with earcon-latency (no per-turn TTS). One is picked at random per wake for
    # variety. Played the instant the wake fires.
    wake_acks: list[bytes] = []
    for phrase in config.tts.ack_phrases:
        try:
            wake_acks.append(await tts.synthesize(phrase))
        except Exception as exc:  # noqa: BLE001 - skip a bad phrase, never block boot
            log.warning("Could not synthesize wake acknowledgement %r: %s", phrase, exc)
    pipeline = VoicePipeline(
        audio_in,
        detector,
        recorder,
        stt,
        orchestrator,
        tts,
        out,
        arbiter,
        preroll_frames=config.recorder.preroll_frames,
        sample_rate=config.audio.sample_rate,
        no_speech_earcon=no_speech(tts.sample_rate),
        wake_earcons=wake_acks,
        end_earcon=descending(tts.sample_rate),
        normalize=config.audio.normalize,
        normalize_target_peak=config.audio.normalize_target_peak,
        normalize_rms_floor=config.audio.normalize_rms_floor,
        min_transcribe_rms=config.audio.min_transcribe_rms,
        conversation_enabled=config.conversation.enabled,
        followup_window_ms=config.conversation.followup_window_ms,
        max_history_turns=config.conversation.max_history_turns,
        # State feed to the monitor TUI, which reads our stdout. Suppressed on an
        # interactive terminal (standalone), where it would just be log noise.
        state_emitter=NullStateEmitter() if sys.stdout.isatty() else StateEmitter(),
    )
    scheduler = ReminderScheduler(
        store, tts, out, arbiter, poll_seconds=config.scheduling.poll_seconds
    )
    # Optional control channel: line commands on stdin (typed commands, live
    # volume) from the monitor TUI when the daemon runs as its child.
    control = ControlChannel(pipeline, out, Speaker(tts, out))

    # Pipeline (wake -> reply), scheduler (proactive reminders), and control
    # channel share the one event loop, audio output, and arbiter; all run until
    # interrupted.
    try:
        await asyncio.gather(pipeline.run(), scheduler.run(), control.run())
    finally:
        store.close()
        await llm.aclose()
        await search.aclose()
        await weather.aclose()


if __name__ == "__main__":
    main()
