"""Daemon entrypoint.

Boots, loads config, sets up logging, resolves audio devices, and (Phase 1)
speaks a greeting through the configured speaker. Later phases wire the full
wake -> STT -> route -> LLM -> TTS pipeline here.
"""

from __future__ import annotations

import asyncio
import logging

from assistant.audio.devices import DeviceSelection, select_devices
from assistant.audio.sounddevice_io import SoundDeviceOut
from assistant.core.config import Config
from assistant.core.logging import setup_logging
from assistant.tts.piper_tts import PiperTTS

log = logging.getLogger("assistant")

GREETING = "Hello, I'm your personal assistant. Phase one is working."


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

    asyncio.run(_greet(config, devices))
    log.info("Boot complete. Exiting.")


async def _greet(config: Config, devices: DeviceSelection) -> None:
    if not config.tts.model_path:
        log.warning("No TTS model configured (tts.model_path); skipping greeting")
        return
    tts = PiperTTS(config.tts.model_path)
    out = SoundDeviceOut(devices.output.index, tts.sample_rate)
    log.info("Speaking greeting: %r", GREETING)
    audio = await tts.synthesize(GREETING)
    await out.play(audio)


if __name__ == "__main__":
    main()
