"""Unit tests for LivekitWakeDetector — no native deps (WakeWordModel injected)."""

from __future__ import annotations

import numpy as np

from assistant.wake.livekit_detector import WINDOW_SAMPLES, LivekitWakeDetector

FRAME_SAMPLES = 1280  # 80 ms @ 16 kHz
FRAMES_TO_FILL = WINDOW_SAMPLES // FRAME_SAMPLES  # 25


class FakeWakeWordModel:
    """Records each predict() input; returns a scripted score for "calcifer"."""

    def __init__(self, score: float = 0.0) -> None:
        self.score = score
        self.calls: list[np.ndarray] = []

    def predict(self, samples: np.ndarray) -> dict[str, float]:
        self.calls.append(samples)
        return {"calcifer": self.score}


def frame(value: int) -> bytes:
    """A 1280-sample frame filled with a per-frame marker, so predict inputs are
    identifiable by content and order."""
    return np.full(FRAME_SAMPLES, value, dtype=np.int16).tobytes()


def feed(det: LivekitWakeDetector, values):
    return [det.process(frame(v)) for v in values]


def test_no_predict_or_event_before_window_full():
    model = FakeWakeWordModel(score=1.0)
    det = LivekitWakeDetector(["m.onnx"], threshold=0.5, model=model)
    events = feed(det, range(FRAMES_TO_FILL - 1))  # 24 frames
    assert model.calls == []
    assert all(e is None for e in events)


def test_predicts_full_ordered_window_on_fill():
    model = FakeWakeWordModel(score=0.0)
    det = LivekitWakeDetector(["m.onnx"], threshold=0.5, model=model)
    feed(det, range(FRAMES_TO_FILL))  # exactly fills the window
    assert len(model.calls) == 1
    got = model.calls[0]
    assert got.dtype == np.int16
    assert got.shape == (WINDOW_SAMPLES,)
    expected = np.concatenate([np.full(FRAME_SAMPLES, i, dtype=np.int16) for i in range(FRAMES_TO_FILL)])
    assert np.array_equal(got, expected)


def test_fires_event_above_threshold_only():
    hot = LivekitWakeDetector(["m.onnx"], threshold=0.5, model=FakeWakeWordModel(score=0.9))
    events = feed(hot, range(FRAMES_TO_FILL))
    assert events[-1] is not None
    assert events[-1].name == "calcifer"
    assert events[-1].score == 0.9

    cold = LivekitWakeDetector(["m.onnx"], threshold=0.5, model=FakeWakeWordModel(score=0.3))
    assert feed(cold, range(FRAMES_TO_FILL))[-1] is None


def test_reset_clears_buffer():
    model = FakeWakeWordModel(score=0.0)
    det = LivekitWakeDetector(["m.onnx"], threshold=0.5, model=model)
    feed(det, range(FRAMES_TO_FILL))  # 1 predict
    assert len(model.calls) == 1
    det.reset()
    feed(det, range(FRAMES_TO_FILL - 1))  # window not refilled -> no new predict
    assert len(model.calls) == 1


def test_score_interval_skips_frames():
    model = FakeWakeWordModel(score=0.0)
    det = LivekitWakeDetector(["m.onnx"], threshold=0.5, score_interval=3, model=model)
    feed(det, range(FRAMES_TO_FILL + 6))  # 7 full-window frames -> predict at #1,#4,#7
    assert len(model.calls) == 3


def test_window_is_the_most_recent_samples():
    model = FakeWakeWordModel(score=0.0)
    det = LivekitWakeDetector(["m.onnx"], threshold=0.5, model=model)
    feed(det, range(30))  # 30 frames; window keeps only the last 25
    last = model.calls[-1]
    expected = np.concatenate(
        [np.full(FRAME_SAMPLES, i, dtype=np.int16) for i in range(30 - FRAMES_TO_FILL, 30)]
    )
    assert np.array_equal(last, expected)
