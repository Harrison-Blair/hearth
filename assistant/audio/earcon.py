"""Generate short non-speech tones (earcons) as raw int16 PCM.

Used for terse audio feedback where speech would be overkill or annoying — e.g.
a brief blip when the assistant wakes but hears nothing. Synthesized in code so
there is no wav asset to ship; the only external input is the output sample rate.
"""

from __future__ import annotations

import numpy as np


def tone(sample_rate: int, *, freq: float = 660.0, ms: int = 180, amplitude: float = 0.25) -> bytes:
    """A single sine beep as int16 PCM at ``sample_rate``.

    ``amplitude`` is deliberately modest; SoundDeviceOut already applies the
    configured output volume, so this should not be near full scale.
    """
    n = int(sample_rate * ms / 1000)
    t = np.arange(n, dtype=np.float32) / sample_rate
    wave = amplitude * np.sin(2 * np.pi * freq * t)
    # Short linear fades top and tail so the beep doesn't click on/off.
    fade = max(1, int(sample_rate * 0.005))
    envelope = np.ones(n, dtype=np.float32)
    envelope[:fade] = np.linspace(0.0, 1.0, fade, dtype=np.float32)
    envelope[-fade:] = np.linspace(1.0, 0.0, fade, dtype=np.float32)
    samples = (wave * envelope * 32767.0).astype(np.int16)
    return samples.tobytes()
