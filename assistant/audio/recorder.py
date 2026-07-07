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
        min_speech_ms: int = 0,
    ) -> None:
        self._vad = webrtcvad.Vad(aggressiveness)
        self._sample_rate = sample_rate
        self._sub = int(sample_rate * _VAD_FRAME_MS / 1000)  # samples per VAD frame
        self._silence_ms = silence_ms
        self._max_ms = max_ms
        self._start_timeout_ms = start_timeout_ms
        self._min_speech_ms = min_speech_ms

    async def record(
        self,
        frames: AsyncIterator[bytes],
        prefix: bytes = b"",
        start_timeout_ms: int | None = None,
        on_level=None,
        cancel_event=None,
    ) -> bytes:
        """Consume frames until end-of-speech; return collected PCM bytes.

        ``prefix`` is pre-roll audio captured just before the wake event,
        prepended so a command spoken right after the wake word isn't clipped.
        ``start_timeout_ms`` overrides the constructor default for this call (the
        follow-up window uses a longer one than the initial capture).
        ``on_level`` (if given) is called once per input frame with the frame's
        int16 RMS, driving the live level meter.
        ``cancel_event`` (if given and set) abandons the capture immediately,
        returning empty so the turn ends without routing anything.

        Returns ``b""`` whenever no speech was detected (cancelled, start
        timeout, or cap reached before speech), so callers can treat empty
        bytes as "nothing said" without transcribing room tone.
        """
        collected = bytearray(prefix)
        speech_started = False
        voiced_ms = 0
        silence_ms = 0
        elapsed_ms = 0
        start_timeout = self._start_timeout_ms if start_timeout_ms is None else start_timeout_ms
        # Cumulative voiced audio required before the capture counts as speech;
        # rejects a lone VAD blip (chair creak) from opening an utterance.
        min_speech = max(self._min_speech_ms, _VAD_FRAME_MS)

        async for frame in frames:
            if cancel_event is not None and cancel_event.is_set():
                log.debug("capture cancelled")
                return b""
            collected += frame
            samples = np.frombuffer(frame, dtype=np.int16)
            if on_level is not None and len(samples):
                on_level(float(np.sqrt(np.mean(samples.astype(np.float32) ** 2))))
            for i in range(0, len(samples) - self._sub + 1, self._sub):
                chunk = samples[i : i + self._sub].tobytes()
                voiced = self._vad.is_speech(chunk, self._sample_rate)
                elapsed_ms += _VAD_FRAME_MS

                if voiced:
                    voiced_ms += _VAD_FRAME_MS
                    if voiced_ms >= min_speech:
                        speech_started = True
                    silence_ms = 0
                elif speech_started:
                    silence_ms += _VAD_FRAME_MS

                if speech_started and silence_ms >= self._silence_ms:
                    return bytes(collected)
                if not speech_started and elapsed_ms >= start_timeout:
                    log.debug("no speech detected within start timeout")
                    return b""
                if elapsed_ms >= self._max_ms:
                    log.debug("max utterance length reached")
                    return bytes(collected) if speech_started else b""

        return bytes(collected) if speech_started else b""
