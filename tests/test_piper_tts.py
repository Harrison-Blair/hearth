"""Unit tests for PiperTTS speaking-rate (length_scale) plumbing.

The real Piper ONNX voice is stubbed so the test runs without a model file: we
only assert that the configured/overridden length_scale reaches Piper's
SynthesisConfig.
"""

from types import SimpleNamespace

import pytest

from assistant.tts import piper_tts


class FakeChunk:
    audio_int16_bytes = b"PCM"


class FakeVoice:
    def __init__(self):
        self.config = SimpleNamespace(sample_rate=22050)
        self.calls = []  # syn_config passed to each synthesize()

    def synthesize(self, text, syn_config=None):
        self.calls.append(syn_config)
        yield FakeChunk()


@pytest.fixture
def fake_voice(monkeypatch):
    voice = FakeVoice()
    monkeypatch.setattr(piper_tts.PiperVoice, "load", staticmethod(lambda _path: voice))
    return voice


async def test_no_rate_passes_no_syn_config(fake_voice):
    tts = piper_tts.PiperTTS("model.onnx")  # no length_scale
    await tts.synthesize("hi")
    assert fake_voice.calls == [None]  # voice default, no override


async def test_configured_rate_flows_to_synthesis(fake_voice):
    tts = piper_tts.PiperTTS("model.onnx", length_scale=1.4)
    await tts.synthesize("hi")
    assert fake_voice.calls[0].length_scale == 1.4


async def test_per_call_override_wins_over_default(fake_voice):
    tts = piper_tts.PiperTTS("model.onnx", length_scale=1.4)
    await tts.synthesize("hi", length_scale=0.8)  # live-test override
    assert fake_voice.calls[0].length_scale == 0.8


async def test_pcm_is_concatenated(fake_voice):
    tts = piper_tts.PiperTTS("model.onnx")
    assert await tts.synthesize("hi") == b"PCM"
