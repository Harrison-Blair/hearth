"""Daemon entrypoint.

Boots, loads config, resolves audio devices, speaks a greeting, then runs the
full voice pipeline: wake word -> record -> transcribe -> route -> LLM -> speak.
"""

from __future__ import annotations

import asyncio
import logging

from assistant.audio.devices import DeviceSelection, select_devices
from assistant.audio.recorder import VadRecorder
from assistant.audio.sounddevice_io import SoundDeviceIn, SoundDeviceOut
from assistant.core.config import Config
from assistant.core.logging import setup_logging
from assistant.core.pipeline import VoicePipeline
from assistant.llm.ollama_provider import OllamaProvider
from assistant.nlu.keyphrase_router import KeyphraseRouter
from assistant.skills.base import SkillRegistry
from assistant.skills.general import GeneralSkill
from assistant.stt.faster_whisper_stt import FasterWhisperSTT
from assistant.tts.piper_tts import PiperTTS
from assistant.wake.openwakeword_detector import OpenWakeWordDetector

log = logging.getLogger("assistant")

GREETING = "Hello, I'm your personal assistant. I'm listening."


def main() -> None:
    config = Config()
    setup_logging(config.logging.level)

    log.info("Personal assistant booting (v%s)", __import__("assistant").__version__)
    log.info(
        "Config: wake=%r model=%s | stt=%s | llm=%s@%s | tts=%s",
        config.wake.phrase,
        config.wake.model_path or config.wake.model_name,
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
    llm = OllamaProvider(config.llm.model, config.llm.host, config.llm.timeout)
    if not await llm.health():
        log.warning(
            "Ollama not ready (host=%s, model=%s); answers will fail until it's up. "
            "Run `ollama serve` and `ollama pull %s`.",
            config.llm.host,
            config.llm.model,
            config.llm.model,
        )
    router = KeyphraseRouter(default_intent="general")
    registry = SkillRegistry()
    registry.register(GeneralSkill(llm, config.llm.system_prompt), default=True)

    # Greeting.
    log.info("Speaking greeting: %r", GREETING)
    await out.play(await tts.synthesize(GREETING))

    # Voice in: wake -> record -> transcribe.
    detector = OpenWakeWordDetector(
        config.wake.model_path, config.wake.model_name, config.wake.threshold
    )
    stt = FasterWhisperSTT(
        config.stt.model, config.stt.compute_type, config.stt.language
    )
    audio_in = SoundDeviceIn(
        devices.input.index,
        sample_rate=config.audio.sample_rate,
        block_size=config.audio.block_size,
        channels=config.audio.channels,
    )
    recorder = VadRecorder(sample_rate=config.audio.sample_rate)

    pipeline = VoicePipeline(
        audio_in, detector, recorder, stt, router, registry, tts, out
    )
    await pipeline.run()


if __name__ == "__main__":
    main()
