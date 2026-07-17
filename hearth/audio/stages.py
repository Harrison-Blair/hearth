"""Stage seams for the audio surface: wake, endpoint, transcribe (listening) and
render, play (speaking).

These are the **interfaces** FTHR-029 (wake), FTHR-030 (endpointing), FTHR-031
(transcription), FTHR-036 (TTS render), and FTHR-038 (device playback) implement,
plus the **trivial doubles** the spine tests drive. No real implementation lives
here.

The shapes are deliberately minimal -- only what the capture loop demonstrably
needs to orchestrate a turn. Real stages adapt to these seams; the seams are not
widened for their convenience (same discipline as PLM-007 FTHR-024's `base.py`).
A frame is whatever the injected `AudioSource` yields -- the surface never
inspects a frame's contents, it only routes it through these stages.

The **output seams** (`Renderer`, `Player`) mirror the input seams above (FTHR-035):
text answer -> `Renderer` -> audio frames -> `Player` -> output device. This feather
ships doubles only; FTHR-036 supplies the real piper `Renderer` and FTHR-038 the
real device `Player` and its lifecycle -- injected through the same seams, exactly
as the real wake/endpoint/STT stages replace the input doubles.
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


# --- output seams: render (text -> frames) and play (frames -> device) --------

# Sentinel for "use the host's system-default output device" (FC-5), mirroring
# how a null `input_device` means the default capture device on the input side.
# The real device selection is FTHR-038; this only names the default target.
SYSTEM_DEFAULT = "system-default"


def resolve_output_device(configured: str | None) -> str:
    """Resolve a configured output device to a concrete player target: an unset
    (null) device means the host's system default (FC-5), mirroring the
    input-device default. Real device selection is FTHR-038 -- this only turns
    the config value into the target a `Player` is opened on."""
    return SYSTEM_DEFAULT if configured is None else configured


@runtime_checkable
class Renderer(Protocol):
    """Turns answer text into audio frames for playback (real TTS is FTHR-036)."""

    def render(self, text: str): ...


@runtime_checkable
class Player(Protocol):
    """Plays rendered audio frames to the output device (real device is FTHR-038)."""

    def play(self, frames) -> None: ...


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


class MarkerRenderer:
    """Render double: returns marker frames for the given text and records every
    text it was asked to render, so the speak call site's 'final answer only'
    rule (FC-8) is assertable. No real TTS -- that is FTHR-036."""

    def __init__(self) -> None:
        self.rendered: list[str] = []

    def render(self, text: str):
        self.rendered.append(text)
        return [("frame", text)]


class RecordingPlayer:
    """Player double: records the frame batches it was told to play and the
    device target it was built for. No real device -- that is FTHR-038."""

    def __init__(self, device: str = SYSTEM_DEFAULT) -> None:
        self.device = device
        self.played: list = []

    def play(self, frames) -> None:
        self.played.append(frames)
