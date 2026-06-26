import numpy as np

from assistant.audio.processing import normalize_peak

TARGET = 0.97
FLOOR = 200.0


def _pcm(samples: np.ndarray) -> bytes:
    return samples.astype(np.int16).tobytes()


def _peak(pcm: bytes) -> int:
    return int(np.abs(np.frombuffer(pcm, dtype=np.int16)).max())


def test_quiet_signal_is_scaled_up_to_target():
    # A sine at ~1/10 full scale, with RMS comfortably above the floor.
    t = np.linspace(0, 1, 16000, endpoint=False)
    quiet = _pcm(np.sin(2 * np.pi * 220 * t) * 3000)

    out = normalize_peak(quiet, TARGET, FLOOR)

    assert abs(_peak(out) - TARGET * 32767) <= 2


def test_near_silent_signal_is_unchanged():
    # RMS below the floor -> treated as silence/noise, returned verbatim.
    near_silent = _pcm(np.full(1600, 50))

    out = normalize_peak(near_silent, TARGET, FLOOR)

    assert out == near_silent


def test_loud_signal_is_not_overdriven():
    t = np.linspace(0, 1, 16000, endpoint=False)
    loud = _pcm(np.sin(2 * np.pi * 220 * t) * 30000)

    out = normalize_peak(loud, TARGET, FLOOR)

    # Brought to the target peak, never clipped past full scale.
    assert _peak(out) <= 32767
    assert abs(_peak(out) - TARGET * 32767) <= 2


def test_empty_input_is_unchanged():
    assert normalize_peak(b"", TARGET, FLOOR) == b""


def test_all_zero_input_is_unchanged():
    zeros = _pcm(np.zeros(1600))
    assert normalize_peak(zeros, TARGET, FLOOR) == zeros
