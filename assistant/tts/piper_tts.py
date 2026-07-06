"""Local text-to-speech via Piper (offline, ONNX)."""

from __future__ import annotations

import asyncio
import logging

from piper import PiperVoice
from piper.config import SynthesisConfig

from assistant.tts.base import TextToSpeech

log = logging.getLogger(__name__)


class PiperTTS(TextToSpeech):
    def __init__(self, model_path: str, length_scale: float | None = None) -> None:
        # Piper auto-loads the matching <model>.onnx.json beside the model.
        self._voice = PiperVoice.load(model_path)
        self.sample_rate = self._voice.config.sample_rate
        # Default speaking rate (Piper length_scale): >1 slower, <1 faster; None
        # leaves the voice's baked-in default.
        self._length_scale = length_scale
        log.info("Loaded Piper voice %s (%d Hz)", model_path, self.sample_rate)

    async def synthesize(self, text: str, length_scale: float | None = None) -> bytes:
        # Piper inference is blocking CPU work; keep the event loop free. A per-call
        # length_scale (used by the live voice test) overrides the configured default.
        rate = length_scale if length_scale is not None else self._length_scale
        return await asyncio.to_thread(self._synthesize, text, rate)

    def _synthesize(self, text: str, length_scale: float | None) -> bytes:
        syn_config = SynthesisConfig(length_scale=length_scale) if length_scale is not None else None
        pcm = bytearray()
        for chunk in self._voice.synthesize(text, syn_config=syn_config):
            pcm += chunk.audio_int16_bytes
        return bytes(pcm)
