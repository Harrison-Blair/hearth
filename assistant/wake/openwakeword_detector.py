"""Local wake-word detection via openWakeWord (ONNX runtime).

Loads one or more models (``WakeConfig.model_refs()``): a series of trained
``.onnx`` paths so several phrases all wake the assistant, a single custom model,
or the bundled default ``models/wake/hey_assistant.onnx`` when none is configured.
Any loaded model firing above threshold triggers a wake.
"""

from __future__ import annotations

import logging

import numpy as np
from openwakeword.model import Model

from assistant.core.events import WakeEvent
from assistant.wake.base import WakeDetector

log = logging.getLogger(__name__)


class OpenWakeWordDetector(WakeDetector):
    def __init__(self, model_refs: list[str], threshold: float) -> None:
        self._model = Model(wakeword_models=model_refs, inference_framework="onnx")
        self._threshold = threshold
        self._keys = list(self._model.models.keys())
        log.info(
            "Wake detector ready: models=%s threshold=%.2f", self._keys, threshold
        )

    def process(self, frame: bytes) -> WakeEvent | None:
        samples = np.frombuffer(frame, dtype=np.int16)
        scores = self._model.predict(samples)
        for name in self._keys:
            score = float(scores[name])
            if score >= self._threshold:
                return WakeEvent(name=name, score=score)
        return None

    def reset(self) -> None:
        self._model.reset()
