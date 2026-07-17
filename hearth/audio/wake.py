"""The wake detector behind FTHR-028's `WakeDetector` seam (FTHR-029).

Implements `stages.py::WakeDetector.detect(frame) -> bool`. It loads the wake
models named in the audio config, scores incoming audio against **each model's
own threshold**, and fires when any model crosses its operating point (PLM-008
FC-2, FC-3).

**The active model set is data, not code.** The detector drives off the config's
`wake_models` list (`[{path, threshold}]`, defined in `config.py` — FTHR-028's
hoisted schema, read here, never extended). One entry fires on one model; three
fire on any of three, by the **same code path** — no single-model special case.

**Per-model threshold, no global.** Each model gates on its own `threshold` from
its config entry. There is no shared/default/averaged threshold anywhere.

**Loading and scoring are separable** (`WakeWordScorer`) from the gating logic
(`WakeDetector`), so a test can drive the multi-model / threshold-gating logic
with synthetic scores while the real `vesta.onnx` load-and-score path is proven
directly against the scorer.
"""
from __future__ import annotations

from collections import deque
from pathlib import Path
from typing import Protocol

from .config import WakeModel

# livekit-wakeword's stateless model wants a ~2-second window at 16 kHz; a shorter
# buffer scores zero. We keep a sliding window just past this and let the model
# handle the rest. (See livekit.wakeword.inference.model.WakeWordModel.predict.)
SAMPLE_RATE = 16000
CHUNK_SAMPLES = SAMPLE_RATE * 2


class Scorer(Protocol):
    """Maps an audio frame to per-model scores ``{name: score}``. The default
    implementation wraps the real livekit-wakeword model; tests inject a
    synthetic scorer to drive the gating logic with controlled scores."""

    def score(self, frame) -> dict[str, float]: ...


class WakeWordScorer:
    """Real load-and-score seam: loads ONNX wake classifiers via
    livekit-wakeword/onnxruntime and scores a sliding ~2s window of frames.

    Model names are the file stems (livekit's own default), matching the keys
    `WakeDetector` gates on. `livekit.wakeword` is imported lazily so importing
    this module never requires the `wake` extra — only constructing the real
    scorer does.
    """

    def __init__(self, paths) -> None:
        from livekit.wakeword import WakeWordModel  # noqa: PLC0415 -- lazy: needs `wake` extra

        import numpy as np  # noqa: PLC0415

        self._np = np
        self._model = WakeWordModel(models=[str(p) for p in paths])
        self._window: deque = deque()
        self._buffered = 0

    def score(self, frame) -> dict[str, float]:
        arr = self._np.asarray(frame).flatten()
        self._window.append(arr)
        self._buffered += arr.size
        # Trim from the front while the window (excluding the oldest frame) still
        # covers a full chunk -- a sliding ~2s window, bounded memory.
        while self._window and self._buffered - self._window[0].size >= CHUNK_SAMPLES:
            self._buffered -= self._window.popleft().size
        chunk = self._np.concatenate(list(self._window))
        return self._model.predict(chunk)


class WakeDetector:
    """Fires when any configured model crosses **its own** threshold.

    Constructed from the config's ordered wake-model list; gating iterates that
    list, so the active set is whatever the config names. Implements FTHR-028's
    `WakeDetector` Protocol (`detect(frame) -> bool`).
    """

    def __init__(self, wake_models: list[WakeModel], *, scorer: Scorer | None = None) -> None:
        self._thresholds = {Path(m.path).stem: m.threshold for m in wake_models}
        self._scorer = scorer or WakeWordScorer([m.path for m in wake_models])

    def detect(self, frame) -> bool:
        scores = self._scorer.score(frame)
        return any(
            name in self._thresholds and score >= self._thresholds[name]
            for name, score in scores.items()
        )
