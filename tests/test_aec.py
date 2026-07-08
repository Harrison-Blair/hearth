import sys

import numpy as np

from assistant.audio.aec import SpeexEchoCanceller, build_aec

# 16 kHz, 20 ms -> 320-sample / 640-byte speex subframes.
SUB = 640


class FakeEchoState:
    """Records (near, far) subframe pairs; echoes the near frame back."""

    def __init__(self):
        self.pairs = []

    def process(self, near, far):
        self.pairs.append((bytes(near), bytes(far)))
        return bytes(near)


def _pcm(n_samples, value=1):
    return np.full(n_samples, value, dtype=np.int16).tobytes()


def _aec(**kwargs):
    state = FakeEchoState()
    return SpeexEchoCanceller(echo_state=state, **kwargs), state


def test_passthrough_when_nothing_is_playing():
    aec, state = _aec()
    near = _pcm(1280, 7)

    assert aec.process(near) == near  # returned as-is
    assert state.pairs == []  # canceller never invoked


def test_pairs_subframes_with_far_chunks_in_order_and_pads_when_exhausted():
    aec, state = _aec()
    aec.feed_far(_pcm(640, 5), rate=16000)  # two 20 ms chunks of far-end
    near = _pcm(1280, 7)  # one mic block = four 20 ms subframes

    out = aec.process(near)

    assert out == near  # identity fake: audio shape preserved
    assert len(state.pairs) == 4
    assert state.pairs[0] == (_pcm(320, 7), _pcm(320, 5))
    assert state.pairs[1] == (_pcm(320, 7), _pcm(320, 5))
    # far ran out mid-frame: remaining subframes cancelled against silence
    assert state.pairs[2] == (_pcm(320, 7), _pcm(320, 0))
    assert state.pairs[3] == (_pcm(320, 7), _pcm(320, 0))


def test_feed_far_resamples_playback_rate_to_mic_rate():
    aec, state = _aec()
    aec.feed_far(_pcm(22050, 5), rate=22050)  # 1 s of playback audio

    aec.process(_pcm(1280, 7))

    # 1 s at 16 kHz = 16000 samples = 50 chunks buffered; 4 consumed by process.
    assert aec.buffered_chunks == 46


def test_extra_delay_prepends_silence_to_the_far_reference():
    aec, state = _aec(extra_delay_ms=40)  # = two 20 ms chunks
    aec.feed_far(_pcm(320, 5), rate=16000)

    aec.process(_pcm(1280, 7))

    fars = [far for _, far in state.pairs]
    assert fars[0] == _pcm(320, 0)  # delay silence first
    assert fars[1] == _pcm(320, 0)
    assert fars[2] == _pcm(320, 5)  # then the actual playback reference


def test_delay_applies_per_clip_not_per_feed():
    aec, state = _aec(extra_delay_ms=20)
    aec.feed_far(_pcm(320, 5), rate=16000)  # clip starts: 1 delay chunk + 1 data
    aec.feed_far(_pcm(320, 6), rate=16000)  # same clip continues: no new delay

    assert aec.buffered_chunks == 3


def test_clear_far_returns_to_passthrough():
    aec, state = _aec()
    aec.feed_far(_pcm(1280, 5), rate=16000)

    aec.clear_far()
    near = _pcm(1280, 7)

    assert aec.process(near) == near
    assert state.pairs == []


def test_trailing_partial_subframe_passes_through_unprocessed():
    aec, state = _aec()
    aec.feed_far(_pcm(1280, 5), rate=16000)
    near = _pcm(480, 7)  # 1.5 subframes

    out = aec.process(near)

    assert len(state.pairs) == 1  # only the whole subframe went through speex
    assert out == near  # identity fake + passthrough tail


def test_build_aec_returns_none_when_speexdsp_is_missing(monkeypatch):
    monkeypatch.setitem(sys.modules, "speexdsp", None)  # forces ImportError

    assert build_aec(sample_rate=16000) is None
