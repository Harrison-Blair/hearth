"""Wake-detection tests (FTHR-029).

Two seams are exercised:

- **Gating logic** — which model fires at which threshold — driven with a
  synthetic scorer (`DictScorer`) so the multi-model / per-model-threshold logic
  is tested without crafting real audio that trips a real model at a precise
  score. This is the data-not-code proof (FC-2) and the no-global-threshold proof
  (FC-3).
- **Real load-and-score** — the committed `vesta.onnx` loaded via
  livekit-wakeword/onnxruntime, proving the real path (AC-4). Hermetic: the model
  is in-repo, no download.

A green suite proves the gating is correct and the model loads and scores; it
does **not** prove wake accuracy on real speech (that a person saying the phrase
trips it and noise does not) -- that is FTHR-033's manual smoke.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from hearth.audio.config import WakeModel
from hearth.audio.wake import WakeDetector, WakeWordScorer

REPO_ROOT = Path(__file__).resolve().parents[1]
VESTA = REPO_ROOT / "models" / "wake" / "vesta.onnx"


class DictScorer:
    """Synthetic scorer: the frame *is* the ``{name: score}`` mapping.

    Lets a test drive the gating logic with controlled per-model scores without
    real audio. The surface treats a frame as opaque, so a mapping frame is a
    legitimate driver for the gating seam.
    """

    def score(self, frame) -> dict[str, float]:
        return dict(frame)


# --- controlled model sets (data, not code) ---------------------------------

THREE_MODELS = [
    WakeModel(path="alpha.onnx", threshold=0.5),
    WakeModel(path="bravo.onnx", threshold=0.8),
    WakeModel(path="charlie.onnx", threshold=0.3),
]
TWO_MODELS = [
    WakeModel(path="low.onnx", threshold=0.4),
    WakeModel(path="high.onnx", threshold=0.9),
]
ONE_REAL_MODEL = [WakeModel(path=str(VESTA), threshold=0.77)]


def _assert_each_gates_independently(models: list[WakeModel]) -> None:
    """Each model fires on and only on **its own** operating point, in one
    running detector -- no single-model special case, no shared threshold."""
    det = WakeDetector(models, scorer=DictScorer())
    for target in models:
        tname = Path(target.path).stem
        # Every model just below its own threshold, target *at* its threshold.
        scores = {Path(m.path).stem: m.threshold - 0.01 for m in models}
        scores[tname] = target.threshold  # >= fires
        assert det.detect(scores) is True, f"{tname} should fire at its threshold"
        # Now target also below its own threshold: nothing fires.
        scores[tname] = target.threshold - 0.01
        assert det.detect(scores) is False, f"{tname} must not fire below threshold"


def test_wake_fires_when_a_model_crosses_its_threshold() -> None:
    """FC-2 single-model case: above the configured threshold fires, below does
    not; the operating point itself (>=) fires."""
    det = WakeDetector(ONE_REAL_MODEL, scorer=DictScorer())
    assert det.detect({"vesta": 0.80}) is True
    assert det.detect({"vesta": 0.50}) is False
    assert det.detect({"vesta": 0.77}) is True  # boundary: at threshold fires


@pytest.mark.parametrize(
    "models",
    [THREE_MODELS, TWO_MODELS, ONE_REAL_MODEL],
    ids=["three-synthetic", "two-synthetic", "one-real"],
)
def test_detection_is_driven_by_the_configured_model_set(models: list[WakeModel]) -> None:
    """Data-not-code proof (FC-2, FC-3): detection is driven by the configured
    set. Runs over multi-model synthetic sets *and* the one-real-model case by
    the **same code path** -- a hardcoded single-model detector cannot satisfy
    the multi-model parameterizations."""
    _assert_each_gates_independently(models)


def test_no_global_threshold_governs_detection() -> None:
    """FC-3: each model gates on its own number, not a global/shared/averaged
    one. Two thresholds 0.4 and 0.9 (avg 0.65); two assertions together defeat
    any single global value (min, max, or average)."""
    det = WakeDetector(TWO_MODELS, scorer=DictScorer())

    # 'low' at 0.5: below any averaged/max global (0.65/0.9) but above its own
    # 0.4 -> MUST fire. A global threshold would (wrongly) not fire here.
    assert det.detect({"low": 0.5, "high": 0.0}) is True

    # 'high' at 0.5: above the min global (0.4) but below its own 0.9 -> must
    # NOT fire. A global min/averaged threshold would (wrongly) fire here.
    assert det.detect({"low": 0.0, "high": 0.5}) is False


def test_real_vesta_model_loads_and_scores() -> None:
    """AC-4: the committed vesta.onnx loads via livekit-wakeword/onnxruntime and
    produces a score for supplied frames -- the real load-and-score path, not
    just the gating logic. Hermetic (in-repo model, no download). Silence is not
    expected to cross the threshold; this proves load+score, not accuracy."""
    scorer = WakeWordScorer([str(VESTA)])
    frame = np.zeros(512, dtype=np.int16)  # matches the source's block size
    scores: dict[str, float] = {}
    # ~2.6s of audio: enough for the model's ~2s window.
    for _ in range(80):
        scores = scorer.score(frame)
    assert "vesta" in scores
    assert isinstance(scores["vesta"], float)
    assert 0.0 <= scores["vesta"] <= 1.0
