"""Renderer tests (FTHR-036, PLM-009 FC-1).

The real renderer behind FTHR-035's `Renderer` seam (`stages.py`), backed by
piper. **Every test MOCKS at the piper library boundary** (`piper.PiperVoice`):
no real voice model is constructed and nothing is downloaded, and no audio device
is touched -- mirroring FTHR-031's faster-whisper mock (Q4=A) on the output side.

What a green run here proves, and what it explicitly does NOT: it proves the
**wiring** -- the configured `voice` reaches piper, the answer text reaches
`synthesize`, and piper's returned audio becomes the frames the seam hands the
`Player`. It does **not** prove the speech is intelligible, natural or renders at
usable latency: that is real-audio quality, provable only in FTHR-039's manual
smoke, not in a CI test here. A green suite is "TTS wired correctly," not "TTS
sounds right."
"""
from __future__ import annotations

import importlib
from unittest.mock import MagicMock, patch

import numpy as np

from hearth.audio.render import PiperRenderer

BOUNDARY = "piper.PiperVoice"


def _chunk(sample_rate, samples):
    """A piper-shaped `AudioChunk`: a `sample_rate` and an int16 mono
    `audio_int16_array` (the two fields the renderer reads to build a frame)."""
    return MagicMock(
        sample_rate=sample_rate,
        audio_int16_array=np.asarray(samples, dtype=np.int16),
    )


def _utterance(*chunks):
    """A synthesised utterance as piper streams it: an iterable of chunks."""
    return iter(chunks)


def test_renderer_synthesises_configured_text_to_frames():
    """FC-1 (real-render half): the renderer takes answer text, hands it to
    piper's `synthesize`, and returns piper's audio as the seam's frames -- the
    (faked) chunks' audio is exactly what comes out."""
    with patch(BOUNDARY) as PiperVoice:
        voice = PiperVoice.load.return_value
        voice.synthesize.return_value = _utterance(_chunk(22050, [1, 2, 3]), _chunk(22050, [4, 5]))

        frames = PiperRenderer("en_US-lessac-medium").render("Hello there")

        # The answer text is what piper was asked to synthesise.
        assert voice.synthesize.call_args.args[0] == "Hello there"
        # One frame per piper chunk, carrying that chunk's audio.
        assert len(frames) == 2
        assert [samples.tolist() for _rate, samples in frames] == [[1, 2, 3], [4, 5]]


def test_configured_voice_and_params_reach_piper():
    """The anti-hollow-mock crux (AC-3): the `voice` named in config is exactly
    what piper is loaded with, and the text is exactly what it synthesises --
    changing the configured voice changes the piper call. Fails if the renderer
    ignores config and hard-codes a voice, or if the wiring is stubbed away."""
    for voice_name in ("en_US-lessac-medium", "en_GB-alba-low"):
        with patch(BOUNDARY) as PiperVoice:
            voice = PiperVoice.load.return_value
            voice.synthesize.return_value = _utterance(_chunk(22050, [1]))

            PiperRenderer(voice_name).render("speak this")

            # The configured voice reaches the piper load call -- and only it.
            PiperVoice.load.assert_called_once_with(voice_name)
            # The text reaches synthesize.
            assert voice.synthesize.call_args.args[0] == "speak this"


def test_rendered_frames_satisfy_the_player_seam_contract():
    """AC-4: the frames the renderer returns are well-formed for the `Player`
    seam -- each carries a positive sample rate and mono int16 PCM samples -- so
    an inter-seam format disagreement fails here, not at FTHR-039's composition."""
    with patch(BOUNDARY) as PiperVoice:
        voice = PiperVoice.load.return_value
        voice.synthesize.return_value = _utterance(
            _chunk(22050, [1, 2, 3]), _chunk(22050, [4, 5, 6])
        )

        frames = PiperRenderer("v").render("hi")

        assert frames  # a non-empty sequence of frames
        for rate, samples in frames:
            assert isinstance(rate, int) and rate > 0
            assert samples.dtype == np.int16
            assert samples.ndim == 1  # mono


def test_rendering_is_hermetic():
    """Hermetic guard (AC-5): importing the module constructs no voice (no eager
    load / download), and every piper construction routes through the patchable
    boundary -- so a real voice-model download or device access can never happen
    in CI. Mirrors FTHR-031's `test_no_real_model_loads_in_ci`."""
    mod = importlib.import_module("hearth.audio.render")
    with patch(BOUNDARY) as PiperVoice:
        importlib.reload(mod)
        # Importing the module must not construct a voice.
        PiperVoice.assert_not_called()

        voice = PiperVoice.load.return_value
        voice.synthesize.return_value = _utterance(_chunk(22050, [1]))
        mod.PiperRenderer("v").render("hi")

        # The only construction went through the patched boundary.
        assert PiperVoice.load.called
