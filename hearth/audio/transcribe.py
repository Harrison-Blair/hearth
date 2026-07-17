"""FTHR-031: offline transcription via faster-whisper.

The real transcriber behind FTHR-028's `Transcriber` seam (`stages.py`): it turns
a captured utterance -- the frames the surface accumulated after a wake -- into
text, offline, with faster-whisper (FC-6).

The model and its parameters are **configuration**, read from the audio surface's
`STTConfig` (`hearth.audio.config`): `model`, `compute_type`, `beam_size`,
`language`. The defaults are the stenographer-proven ones
(`Systran/faster-distil-whisper-medium.en`, `int8`, beam 5, English); the Pi can
swap to a lighter model without a code edit.

Scope (PLM-008): the model is constructed once and used -- **no lazy loading,
idle-unload or residency policy**, which the user explicitly excluded when scoping
PLM-008. faster-whisper is imported lazily (like `source.py`'s `sounddevice`) so
importing this module never requires the `stt` extra and never loads a model.
"""
from __future__ import annotations

import numpy as np

from hearth.audio.config import STTConfig


class WhisperTranscriber:
    """FTHR-028's `Transcriber` seam, backed by faster-whisper.

    The faster-whisper model is built from config in `__init__` and reused for
    every utterance. `transcribe` joins the captured frames into the mono float32
    signal faster-whisper expects and returns the recognised text."""

    def __init__(self, config: STTConfig) -> None:
        from faster_whisper import WhisperModel  # lazy: `stt` extra not needed to import

        self._beam_size = config.beam_size
        self._language = config.language
        self._model = WhisperModel(config.model, compute_type=config.compute_type)

    def transcribe(self, frames) -> str:
        segments, _info = self._model.transcribe(
            _to_audio(frames),
            beam_size=self._beam_size,
            language=self._language,
        )
        return "".join(segment.text for segment in segments).strip()


def _to_audio(frames) -> np.ndarray:
    """Join the accumulated capture frames into the 1-D float32 signal
    faster-whisper takes.

    FTHR-028's `LiveAudioSource` yields float32 blocks shaped
    ``(blocksize, channels)`` at 16 kHz mono -- already faster-whisper's expected
    sample rate and dtype, so this only concatenates and flattens; no resampling
    or dtype conversion is invented here. (A format mismatch would be a finding
    against FTHR-028's source seam, not fixed by a conversion here.)"""
    if not frames:
        return np.zeros(0, dtype=np.float32)
    return np.concatenate([np.asarray(frame, dtype=np.float32).reshape(-1) for frame in frames])
