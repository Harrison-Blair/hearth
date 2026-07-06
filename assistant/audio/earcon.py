"""Generate short non-speech tones (earcons) as raw int16 PCM.

Used for terse audio feedback where speech would be overkill or annoying — e.g.
a brief blip when the assistant wakes but hears nothing. Synthesized in code so
there is no wav asset to ship; the only external input is the output sample rate.
"""

from __future__ import annotations

import numpy as np


def tone(sample_rate: int, *, freq: float = 660.0, ms: int = 180, amplitude: float = 0.22) -> bytes:
    """A single sine beep as int16 PCM at ``sample_rate``.

    ``amplitude`` is deliberately modest; SoundDeviceOut already applies the
    configured output volume, so this should not be near full scale.
    """
    n = int(sample_rate * ms / 1000)
    t = np.arange(n, dtype=np.float32) / sample_rate
    wave = amplitude * np.sin(2 * np.pi * freq * t)
    # Longer raised-cosine fades top and tail so the beep eases on/off rather than
    # clicking — a soft attack is most of what keeps an earcon from sounding harsh.
    fade = max(1, int(sample_rate * 0.012))
    ramp = 0.5 * (1.0 - np.cos(np.linspace(0.0, np.pi, fade, dtype=np.float32)))
    envelope = np.ones(n, dtype=np.float32)
    envelope[:fade] = ramp
    envelope[-fade:] = ramp[::-1]
    samples = (wave * envelope * 32767.0).astype(np.int16)
    return samples.tobytes()


def chime(sample_rate: int) -> bytes:
    """A short two-note ascending chime as int16 PCM at ``sample_rate``."""
    return tone(sample_rate, freq=660.0, ms=120) + tone(sample_rate, freq=880.0, ms=160)


def descending(sample_rate: int) -> bytes:
    """A soft two-note *falling* earcon: 'I've stopped listening / got it'.

    The mirror of the rising wake cue — falling reads as "closing", so paired with
    an opening cue the two bracket the listening window unambiguously.
    """
    return tone(sample_rate, freq=660.0, ms=130, amplitude=0.20) + tone(
        sample_rate, freq=440.0, ms=180, amplitude=0.20
    )


def no_speech(sample_rate: int) -> bytes:
    """A single soft low note for 'woke but heard nothing' — gentle and neutral,
    distinct from the descending 'got it' cue so the two aren't confused."""
    return tone(sample_rate, freq=400.0, ms=220, amplitude=0.18)
