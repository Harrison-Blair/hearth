import numpy as np

from assistant.audio.earcon import chime, descending, no_speech, tone

SR = 22050


def _samples(pcm):
    return np.frombuffer(pcm, dtype=np.int16)


def test_earcons_are_nonempty_int16_pcm():
    for pcm in (tone(SR), chime(SR), descending(SR), no_speech(SR)):
        assert isinstance(pcm, bytes)
        assert len(pcm) % 2 == 0  # whole int16 samples
        assert len(pcm) > 0


def test_earcons_stay_below_full_scale():
    # Modest amplitude + soft fades: nothing should clip near full scale (harsh).
    for pcm in (chime(SR), descending(SR), no_speech(SR)):
        assert int(np.abs(_samples(pcm)).max()) < 32000


def test_descending_and_no_speech_are_distinct():
    # The "got it" cue and the "heard nothing" cue must not sound identical.
    assert descending(SR) != no_speech(SR)
