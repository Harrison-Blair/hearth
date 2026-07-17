"""Transcriber tests (FTHR-031, PLM-008 FC-6).

The real transcriber behind FTHR-028's `Transcriber` seam, backed by
faster-whisper. **Every test MOCKS at the faster-whisper library boundary**
(`faster_whisper.WhisperModel`): no real model is constructed and nothing is
downloaded (the default model is ~800 MB).

What a green run here proves, and what it explicitly does NOT (decomposition
Q4=A): it proves the **wiring** -- the configured model / compute_type /
beam_size / language reach faster-whisper, and the returned transcript flows
onward for submission as the turn. It does **not** prove faster-whisper
transcribes audio correctly; real supplied-audio-to-expected-text is FTHR-033's
manual smoke, not a CI test here.
"""
from __future__ import annotations

import importlib
from unittest.mock import MagicMock, patch

import numpy as np

from hearth.audio.config import STTConfig
from hearth.audio.transcribe import WhisperTranscriber

BOUNDARY = "faster_whisper.WhisperModel"


def _segments(*texts):
    """A faster-whisper-shaped segment iterable: objects with a `.text`."""
    return iter([MagicMock(text=t) for t in texts])


def _utterance():
    """An utterance as FTHR-028's `LiveAudioSource` yields it: a list of float32
    blocks, mono (shape ``(blocksize, channels)``), 16 kHz."""
    return [np.zeros((512, 1), dtype=np.float32) for _ in range(3)]


def test_configured_model_params_reach_faster_whisper():
    """The Q4=A crux: the config's model, compute_type, beam_size and language
    are exactly what reach the library -- a wrong config value is caught here.

    Checked twice: with the stenographer defaults (AC-2 -- those specific values
    reach the library) and with distinct custom values (proving the params are
    read from config, not hardcoded)."""
    cases = [
        (
            STTConfig(),
            "Systran/faster-distil-whisper-medium.en",
            "int8",
            5,
            "en",
        ),
        (
            STTConfig(model="tiny.en", compute_type="float16", beam_size=3, language="es"),
            "tiny.en",
            "float16",
            3,
            "es",
        ),
    ]
    for config, model_name, compute_type, beam_size, language in cases:
        with patch(BOUNDARY) as WhisperModel:
            model = WhisperModel.return_value
            model.transcribe.return_value = (_segments("x"), MagicMock())

            WhisperTranscriber(config).transcribe(_utterance())

            # model name + compute_type reach the constructor
            WhisperModel.assert_called_once_with(model_name, compute_type=compute_type)
            # beam_size + language reach the transcribe call
            _pos, kwargs = model.transcribe.call_args
            assert kwargs["beam_size"] == beam_size
            assert kwargs["language"] == language


def test_returned_transcript_flows_to_the_turn():
    """The (faked) model returns known text; the transcriber returns that text,
    which is what the surface submits as the turn (AC-3)."""
    with patch(BOUNDARY) as WhisperModel:
        model = WhisperModel.return_value
        model.transcribe.return_value = (_segments(" Hello", " there"), MagicMock())

        result = WhisperTranscriber(STTConfig()).transcribe(_utterance())

    assert result == "Hello there"


def test_no_real_model_loads_in_ci():
    """Hermetic guard (AC-5): importing the module constructs no model (no eager
    load), and every faster-whisper construction routes through the patchable
    boundary -- so a real ~800 MB download can never happen in CI. An accidental
    eager instantiation at import is caught by ``assert_not_called`` after the
    reload."""
    mod = importlib.import_module("hearth.audio.transcribe")
    with patch(BOUNDARY) as WhisperModel:
        importlib.reload(mod)
        # Importing the module must not construct a model.
        WhisperModel.assert_not_called()

        model = WhisperModel.return_value
        model.transcribe.return_value = (_segments("x"), MagicMock())
        mod.WhisperTranscriber(STTConfig()).transcribe(_utterance())

        # The only construction went through the patched boundary.
        assert WhisperModel.called


def test_no_model_lifecycle_management():
    """Scope pin (AC-6): the transcriber constructs and uses the model, nothing
    more -- no lazy loading, idle-unload or residency policy (excluded from FC-6
    when PLM-008 was scoped). The model is built once in ``__init__`` and reused
    across utterances, and the transcriber exposes no lifecycle surface."""
    with patch(BOUNDARY) as WhisperModel:
        model = WhisperModel.return_value
        model.transcribe.side_effect = [
            (_segments("a"), MagicMock()),
            (_segments("b"), MagicMock()),
        ]

        transcriber = WhisperTranscriber(STTConfig())
        # Built once, eagerly in __init__ -- not lazily on first transcribe.
        assert WhisperModel.call_count == 1

        transcriber.transcribe(_utterance())
        transcriber.transcribe(_utterance())
        # Reused across turns: no reconstruct, no unload/reload between them.
        assert WhisperModel.call_count == 1

        # No model-lifecycle surface on the transcriber.
        for attr in ("load", "unload", "close", "reload", "shutdown", "warm", "evict"):
            assert not hasattr(transcriber, attr)
