"""Voice pipeline orchestrator.

Phase 2b: listen for the wake word, record the following utterance, transcribe
it, and log the transcript. Later phases route the transcript to a skill and
speak the result.
"""

from __future__ import annotations

import logging
from collections import deque

import numpy as np

from assistant.audio.base import AudioIn
from assistant.audio.recorder import VadRecorder
from assistant.stt.base import SpeechToText
from assistant.wake.base import WakeDetector

log = logging.getLogger(__name__)

# ~0.5s of 80ms frames kept before the wake event, so a command spoken
# immediately after the wake word (clipped by detection latency) is recovered.
_PREROLL_FRAMES = 6


class VoicePipeline:
    def __init__(
        self,
        audio_in: AudioIn,
        detector: WakeDetector,
        recorder: VadRecorder,
        stt: SpeechToText,
    ) -> None:
        self._audio_in = audio_in
        self._detector = detector
        self._recorder = recorder
        self._stt = stt

    async def run(self) -> None:
        frames = self._audio_in.stream()
        preroll: deque[bytes] = deque(maxlen=_PREROLL_FRAMES)
        log.info("Listening for wake word...")
        async for frame in frames:
            preroll.append(frame)
            event = self._detector.process(frame)
            if event is None:
                continue

            log.info("Wake word detected: %s (%.2f)", event.name, event.score)
            pcm = await self._recorder.record(frames, prefix=b"".join(preroll))
            preroll.clear()
            samples = np.frombuffer(pcm, dtype=np.int16)
            rms = float(np.sqrt(np.mean(samples.astype(np.float32) ** 2))) if len(samples) else 0.0
            log.info("Captured %.1fs (rms=%.0f, peak=%d)", len(samples) / 16000, rms, int(np.abs(samples).max()) if len(samples) else 0)
            transcript = await self._stt.transcribe(pcm)
            if transcript:
                log.info("Heard: %r", transcript)
            else:
                log.info("No speech captured.")

            self._detector.reset()
            log.info("Listening for wake word...")
