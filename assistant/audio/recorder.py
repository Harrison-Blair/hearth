"""End-of-speech utterance recording via WebRTC VAD.

After a wake event the pipeline hands the live frame stream to ``record()``,
which accumulates audio until it sees enough trailing silence (or hits a cap).
"""

from __future__ import annotations

import logging
from typing import AsyncIterator

import numpy as np
import webrtcvad

log = logging.getLogger(__name__)

# webrtcvad accepts only 10/20/30ms frames; we use 20ms sub-frames.
_VAD_FRAME_MS = 20


class VadRecorder:
    def __init__(
        self,
        sample_rate: int = 16000,
        aggressiveness: int = 2,
        silence_ms: int = 800,
        max_ms: int = 10000,
        start_timeout_ms: int = 3000,
    ) -> None:
        self._vad = webrtcvad.Vad(aggressiveness)
        self._sample_rate = sample_rate
        self._sub = int(sample_rate * _VAD_FRAME_MS / 1000)  # samples per VAD frame
        self._silence_ms = silence_ms
        self._max_ms = max_ms
        self._start_timeout_ms = start_timeout_ms

    async def record(self, frames: AsyncIterator[bytes], prefix: bytes = b"") -> bytes:
        """Consume frames until end-of-speech; return collected PCM bytes.

        ``prefix`` is pre-roll audio captured just before the wake event,
        prepended so a command spoken right after the wake word isn't clipped.
        """
        collected = bytearray(prefix)
        speech_started = False
        silence_ms = 0
        elapsed_ms = 0

        async for frame in frames:
            collected += frame
            samples = np.frombuffer(frame, dtype=np.int16)
            for i in range(0, len(samples) - self._sub + 1, self._sub):
                chunk = samples[i : i + self._sub].tobytes()
                voiced = self._vad.is_speech(chunk, self._sample_rate)
                elapsed_ms += _VAD_FRAME_MS

                if voiced:
                    speech_started = True
                    silence_ms = 0
                elif speech_started:
                    silence_ms += _VAD_FRAME_MS

                if speech_started and silence_ms >= self._silence_ms:
                    return bytes(collected)
                if not speech_started and elapsed_ms >= self._start_timeout_ms:
                    log.debug("no speech detected within start timeout")
                    return bytes(collected)
                if elapsed_ms >= self._max_ms:
                    log.debug("max utterance length reached")
                    return bytes(collected)

        return bytes(collected)
