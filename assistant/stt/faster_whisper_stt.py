"""Local speech-to-text via faster-whisper (CTranslate2, CPU)."""

from __future__ import annotations

import asyncio
import logging

import numpy as np
from faster_whisper import WhisperModel

from assistant.stt.base import SpeechToText

log = logging.getLogger(__name__)


class FasterWhisperSTT(SpeechToText):
    def __init__(
        self,
        model: str = "base.en",
        compute_type: str = "int8",
        language: str = "en",
        beam_size: int = 1,
    ) -> None:
        # First load downloads the model from HF and caches it.
        self._model = WhisperModel(model, device="cpu", compute_type=compute_type)
        self._language = language
        self._beam_size = beam_size
        log.info("STT ready: faster-whisper %s (%s)", model, compute_type)

    async def transcribe(self, audio: bytes) -> str:
        return await asyncio.to_thread(self._transcribe, audio)

    def _transcribe(self, audio: bytes) -> str:
        samples = np.frombuffer(audio, dtype=np.int16).astype(np.float32) / 32768.0
        segments, _ = self._model.transcribe(
            samples, language=self._language, beam_size=self._beam_size
        )
        return " ".join(seg.text.strip() for seg in segments).strip()
