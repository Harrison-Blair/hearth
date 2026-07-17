"""Stage seams for the listening spine: wake, endpoint, transcribe.

These are the **interfaces** FTHR-029 (wake), FTHR-030 (endpointing), and
FTHR-031 (transcription) implement, plus the **trivial doubles** the spine tests
drive. No real implementation lives here.

The shapes are deliberately minimal -- only what the capture loop demonstrably
needs to orchestrate a turn. Real stages adapt to these seams; the seams are not
widened for their convenience (same discipline as PLM-007 FTHR-024's `base.py`).
A frame is whatever the injected `AudioSource` yields -- the surface never
inspects a frame's contents, it only routes it through these stages.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class WakeDetector(Protocol):
    """Decides, per frame, whether the wake word just fired."""

    def detect(self, frame) -> bool: ...


@runtime_checkable
class Endpointer(Protocol):
    """Consumes utterance frames after a wake and reports when the utterance is
    complete. `reset()` is called at the start of each new utterance."""

    def accept(self, frame) -> bool: ...

    def reset(self) -> None: ...


@runtime_checkable
class Transcriber(Protocol):
    """Turns a captured utterance (the accumulated frames) into text."""

    def transcribe(self, frames) -> str: ...


# --- trivial doubles for the spine tests -------------------------------------


class ScriptedWakeDetector:
    """Fires when a frame equals its trigger sentinel."""

    def __init__(self, trigger="wake") -> None:
        self._trigger = trigger

    def detect(self, frame) -> bool:
        return frame == self._trigger


class ScriptedEndpointer:
    """Reports the utterance complete when a frame equals its sentinel."""

    def __init__(self, sentinel="endpoint") -> None:
        self._sentinel = sentinel

    def accept(self, frame) -> bool:
        return frame == self._sentinel

    def reset(self) -> None:
        return None


class FixedTranscriber:
    """Always returns the same transcript, ignoring the frames."""

    def __init__(self, text: str) -> None:
        self._text = text

    def transcribe(self, frames) -> str:
        return self._text
