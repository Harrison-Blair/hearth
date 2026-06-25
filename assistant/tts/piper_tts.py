"""Local text-to-speech via Piper (offline, ONNX)."""

from __future__ import annotations

import asyncio
import logging

from piper import PiperVoice

from assistant.tts.base import TextToSpeech

log = logging.getLogger(__name__)


class PiperTTS(TextToSpeech):
    def __init__(self, model_path: str) -> None:
        # Piper auto-loads the matching <model>.onnx.json beside the model.
        self._voice = PiperVoice.load(model_path)
        self.sample_rate = self._voice.config.sample_rate
        log.info("Loaded Piper voice %s (%d Hz)", model_path, self.sample_rate)

    async def synthesize(self, text: str) -> bytes:
        # Piper inference is blocking CPU work; keep the event loop free.
        return await asyncio.to_thread(self._synthesize, text)

    def _synthesize(self, text: str) -> bytes:
        pcm = bytearray()
        for chunk in self._voice.synthesize(text):
            pcm += chunk.audio_int16_bytes
        return bytes(pcm)
