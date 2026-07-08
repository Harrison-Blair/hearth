"""Lightweight PCM preprocessing applied before transcription."""

from __future__ import annotations

import numpy as np


def normalize_peak(pcm: bytes, target_peak: float, rms_floor: float) -> bytes:
    """Peak-normalize int16 mono PCM so its loudest sample reaches `target_peak`
    of full scale.

    Gated by `rms_floor`: captures whose RMS is below the floor (silence/noise
    only) are returned unchanged, so we don't amplify a quiet room up into a roar.
    Empty or all-zero input is also returned as-is.
    """
    samples = np.frombuffer(pcm, dtype=np.int16)
    if not len(samples):
        return pcm

    floats = samples.astype(np.float32)
    rms = float(np.sqrt(np.mean(floats**2)))
    peak = float(np.abs(floats).max())
    if peak == 0.0 or rms < rms_floor:
        return pcm

    gain = (target_peak * 32767.0) / peak
    scaled = np.clip(floats * gain, -32768.0, 32767.0).astype(np.int16)
    return scaled.tobytes()
