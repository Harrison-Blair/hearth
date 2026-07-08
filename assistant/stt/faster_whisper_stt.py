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
        beam_size: int = 5,
        vad_filter: bool = True,
        condition_on_previous_text: bool = False,
        initial_prompt: str | None = None,
        device: str = "cpu",
        cpu_threads: int = 0,
        no_speech_threshold: float = 0.6,
        log_prob_threshold: float = -1.0,
    ) -> None:
        # First load downloads the model from HF and caches it.
        self._model = WhisperModel(
            model, device=device, compute_type=compute_type, cpu_threads=cpu_threads
        )
        self._language = language
        self._beam_size = beam_size
        self._vad_filter = vad_filter
        self._condition_on_previous_text = condition_on_previous_text
        self._initial_prompt = initial_prompt
        self._no_speech_threshold = no_speech_threshold
        self._log_prob_threshold = log_prob_threshold
        log.info("STT ready: faster-whisper %s (%s)", model, compute_type)

    async def transcribe(self, audio: bytes) -> str:
        return await asyncio.to_thread(self._transcribe, audio)

    def _transcribe(self, audio: bytes) -> str:
        samples = np.frombuffer(audio, dtype=np.int16).astype(np.float32) / 32768.0
        if not len(samples):
            return ""
        segments, _ = self._model.transcribe(
            samples,
            language=self._language,
            beam_size=self._beam_size,
            vad_filter=self._vad_filter,
            condition_on_previous_text=self._condition_on_previous_text,
            initial_prompt=self._initial_prompt or None,
            no_speech_threshold=self._no_speech_threshold,
            log_prob_threshold=self._log_prob_threshold,
        )
        # Whisper only skips a segment when no_speech_prob is high AND avg_logprob
        # is low; confident hallucinations ("Thank you.") pass that test, so drop
        # likely-silent segments independently.
        return " ".join(
            seg.text.strip()
            for seg in segments
            if seg.no_speech_prob <= self._no_speech_threshold
        ).strip()
