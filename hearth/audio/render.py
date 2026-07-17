"""FTHR-036: text-to-speech rendering via piper.

The real renderer behind FTHR-035's `Renderer` seam (`stages.py`): it turns the
engine's final-answer text into audio frames the `Player` (FTHR-038) plays,
offline, with piper (PLM-009 FC-1). This is the speaking-side mirror of FTHR-031
(STT via faster-whisper): a real library wired behind a seam the surface already
knows, mocked at its boundary in CI so the wiring is proven hermetically -- no
model, no download, no sound card.

The voice is **configuration** -- FTHR-035's `voice` key (`AudioSettings.voice`).
It has no shipped default; an *absent* voice is FTHR-037's first-run acquisition
error, not this feather's concern. This renderer loads and renders with a voice
that is present. piper is imported lazily (like `transcribe.py`'s faster-whisper
and `source.py`'s sounddevice) so importing this module never requires the `tts`
extra and never loads a voice model.

A rendered **frame** is a ``(sample_rate, samples)`` pair: a positive sample rate
and the mono int16 PCM samples piper produced at that rate. The rate travels *with*
the frames because the `Player` (FTHR-038, a separate object) has no other channel
to learn it -- the surface hands frames from renderer to player untouched, never
inspecting them (`surface.py::_speak`). This keeps FTHR-035's opaque-frame seam
sufficient (a self-describing frame needs no seam change) and keeps the `Player`
decoupled from piper's own types. piper streams the utterance as multiple chunks;
each becomes one frame, so playback can be interrupted between frames (FTHR-038's
barge-in).
"""
from __future__ import annotations


class PiperRenderer:
    """FTHR-035's `Renderer` seam, backed by piper.

    The piper voice is loaded from config in `__init__` and reused for every
    answer. `render` synthesises the given text and returns piper's audio as the
    seam's ``(sample_rate, samples)`` frames."""

    def __init__(self, voice: str) -> None:
        from piper import PiperVoice  # lazy: `tts` extra not needed to import

        self._voice = PiperVoice.load(voice)

    def render(self, text: str):
        return [
            (chunk.sample_rate, chunk.audio_int16_array)
            for chunk in self._voice.synthesize(text)
        ]
