"""Local wake-word detection via livekit-wakeword (ONNX runtime).

Loads one or more trained ``.onnx`` classifiers (``WakeConfig.model_refs()``) so
several phrases all wake the assistant. Any loaded model scoring above threshold
triggers a wake.

livekit's ``WakeWordModel`` is **stateless**: each ``predict`` recomputes mel +
embedding features over a full ~2 s window (32,000 samples @ 16 kHz) and returns
``{model_stem: score}``. We accumulate incoming frames into a rolling window and
score once it is full, so ``predict`` never sees a short buffer (which it scores
as 0.0). ``score_interval`` skips frames to trade a little latency for CPU on the
Pi 5, since each predict recomputes the whole window.
"""

from __future__ import annotations

import logging

import numpy as np

from assistant.core.events import WakeEvent
from assistant.wake.base import WakeDetector

log = logging.getLogger(__name__)

WINDOW_SAMPLES = 32000  # model-intrinsic ~2 s @ 16 kHz — not config
WINDOW_BYTES = WINDOW_SAMPLES * 2  # int16


class LivekitWakeDetector(WakeDetector):
    def __init__(
        self,
        model_refs: list[str],
        threshold: float,
        score_interval: int = 1,
        model: object | None = None,
    ) -> None:
        if model is None:
            from livekit.wakeword import WakeWordModel

            model = WakeWordModel(models=model_refs)
        self._model = model
        self._threshold = threshold
        self._score_interval = score_interval
        self._buf = bytearray()
        self._frames_full = 0
        log.info(
            "Wake detector ready: models=%s threshold=%.2f interval=%d",
            model_refs,
            threshold,
            score_interval,
        )

    def process(self, frame: bytes) -> WakeEvent | None:
        self._buf.extend(frame)
        if len(self._buf) > WINDOW_BYTES:
            del self._buf[:-WINDOW_BYTES]
        if len(self._buf) < WINDOW_BYTES:
            return None
        # Window is full; score every score_interval-th frame from the first.
        if self._frames_full % self._score_interval:
            self._frames_full += 1
            return None
        self._frames_full += 1
        samples = np.frombuffer(bytes(self._buf), dtype=np.int16)
        scores = self._model.predict(samples)
        for name, score in scores.items():
            if float(score) >= self._threshold:
                return WakeEvent(name=name, score=float(score))
        return None

    def reset(self) -> None:
        self._buf.clear()
        self._frames_full = 0
