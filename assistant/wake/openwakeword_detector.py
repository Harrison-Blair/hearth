"""Local wake-word detection via openWakeWord (ONNX runtime).

Loads a custom trained model when ``model_path`` is set, otherwise a stock
bootstrap model by name (e.g. ``hey_jarvis``) so voice-in works before the
``hey assistant`` model is trained.
"""

from __future__ import annotations

import logging

import numpy as np
from openwakeword.model import Model

from assistant.core.events import WakeEvent
from assistant.wake.base import WakeDetector

log = logging.getLogger(__name__)


class OpenWakeWordDetector(WakeDetector):
    def __init__(
        self, model_path: str | None, model_name: str, threshold: float
    ) -> None:
        model_ref = model_path or model_name
        self._model = Model(wakeword_models=[model_ref], inference_framework="onnx")
        self._threshold = threshold
        self._keys = list(self._model.models.keys())
        log.info(
            "Wake detector ready: model=%s threshold=%.2f", self._keys, threshold
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
