"""Audio surface *speaking* extension tests (FTHR-035).

Exercise the speaking half added to the single audio surface FTHR-028 stood up:
the `Renderer`/`Player` output seams, the speak call site (final answer only),
the `[heard]`/`[spoken]` tagged presentation, and the speaking config keys. All
proven with **doubles** -- no piper, no real device, no sound. Real speech is
FTHR-036, real playback/barge-in FTHR-038, first-run voice acquisition FTHR-037.
"""
from __future__ import annotations

import asyncio
import os
import re


def _clear_hearth_env(monkeypatch):
    for key in list(os.environ):
        if key.startswith("HEARTH_"):
            monkeypatch.delenv(key, raising=False)


# --- AC-2 / FC-1: answer -> Renderer -> Player through the injected seams -----


async def test_final_answer_is_rendered_and_played_through_the_seams():
    """A turn's final answer flows answer -> `Renderer` -> `Player` through the
    injected output seams, both doubles. The FC-1 seam proof (real render/play
    are FTHR-036/038)."""
    from hearth.audio.source import SuppliedFramesSource
    from hearth.audio.stages import (
        FixedTranscriber,
        MarkerRenderer,
        RecordingPlayer,
        ScriptedEndpointer,
        ScriptedWakeDetector,
    )
    from hearth.audio.surface import AudioSurface

    renderer = MarkerRenderer()
    player = RecordingPlayer()

    async def submit(transcript: str) -> list[dict]:
        return [
            {"type": "answer", "turn_id": "t", "text": "hello there"},
            {"type": "done", "turn_id": "t"},
        ]

    surface = AudioSurface(
        source=SuppliedFramesSource(["wake", "endpoint"]),
        wake=ScriptedWakeDetector(trigger="wake"),
        endpointer=ScriptedEndpointer(sentinel="endpoint"),
        transcriber=FixedTranscriber("what time is it"),
        renderer=renderer,
        player=player,
        submit=submit,
        present=lambda _m: None,
    )

    await asyncio.wait_for(surface.run(), timeout=2.0)

    # The final answer was rendered, and exactly the produced frames were played.
    assert renderer.rendered == ["hello there"]
    assert player.played == [renderer.render("hello there")]


# --- AC-3 / FC-8: tool activity is never rendered to speech ------------------


async def test_tool_activity_is_never_rendered_to_speech():
    """A turn that produces tool activity plus a final answer: the recording
    renderer double saw the final answer and **not** the tool activity. FC-8,
    tested at the call site that enforces it. Tool activity is still *presented*
    (visually), just never spoken."""
    from hearth.audio.source import SuppliedFramesSource
    from hearth.audio.stages import (
        FixedTranscriber,
        MarkerRenderer,
        RecordingPlayer,
        ScriptedEndpointer,
        ScriptedWakeDetector,
    )
    from hearth.audio.surface import AudioSurface

    renderer = MarkerRenderer()
    presented: list[str] = []

    async def submit(transcript: str) -> list[dict]:
        return [
            {"type": "tool_activity", "turn_id": "t", "label": "consulting the brain"},
            {"type": "answer", "turn_id": "t", "text": "it is noon"},
            {"type": "done", "turn_id": "t"},
        ]

    surface = AudioSurface(
        source=SuppliedFramesSource(["wake", "endpoint"]),
        wake=ScriptedWakeDetector(trigger="wake"),
        endpointer=ScriptedEndpointer(sentinel="endpoint"),
        transcriber=FixedTranscriber("what time is it"),
        renderer=renderer,
        player=RecordingPlayer(),
        submit=submit,
        present=presented.append,
    )

    await asyncio.wait_for(surface.run(), timeout=2.0)

    # Only the final answer reached the renderer; the tool activity never did.
    assert renderer.rendered == ["it is noon"]
    assert "consulting the brain" not in renderer.rendered
    # The tool activity WAS shown to the user, just not spoken.
    joined = "\n".join(presented)
    assert "consulting the brain" in joined


# --- AC-4 / FC-9: heard vs spoken, distinct tags and colours -----------------


def _first_color(styled: str) -> str:
    match = re.search(r"\033\[(\d+)m", styled)
    assert match is not None, f"no ANSI colour in {styled!r}"
    return match.group(1)


def test_heard_and_spoken_presented_with_distinct_tags_and_colours():
    """The presentation function renders a heard line and a spoken line with
    different tags and different colours -- a pure function of (text, tag), no
    device. FC-9."""
    from hearth.audio.surface import present_line

    heard = present_line("what time is it", "heard")
    spoken = present_line("it is noon", "spoken")

    # Distinct tags.
    assert "heard" in heard and "heard" not in spoken
    assert "spoken" in spoken and "spoken" not in heard
    # The underlying text is carried through.
    assert "what time is it" in heard and "it is noon" in spoken
    # Distinct colours.
    assert _first_color(heard) != _first_color(spoken)


# --- AC-5 / FC-5: output device defaults to the system default ---------------


def test_output_device_defaults_to_system_default_when_unset(tmp_path, monkeypatch):
    """With no output device configured, the surface's resolved player target is
    the system default; with one set, it is that device. Proven at the
    config/seam boundary with a double (real device selection is FTHR-038). FC-5."""
    from hearth.audio.stages import SYSTEM_DEFAULT, RecordingPlayer, resolve_output_device

    # Pure resolution: unset (None) -> system default; set -> that device.
    assert resolve_output_device(None) == SYSTEM_DEFAULT
    assert resolve_output_device("hw:CARD=Device") == "hw:CARD=Device"

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    monkeypatch.setattr("hearth.config.CONFIG_DIR", config_dir)
    _clear_hearth_env(monkeypatch)

    from hearth.audio.config import AudioSettings

    # No output_device key: resolves to the system default at the seam.
    (config_dir / "audio.yaml").write_text("voice: en_US-amy\n")
    settings = AudioSettings()
    assert settings.output_device is None
    default_player = RecordingPlayer(device=resolve_output_device(settings.output_device))
    assert default_player.device == SYSTEM_DEFAULT

    # A configured device is threaded through to the player target.
    (config_dir / "audio.yaml").write_text("voice: en_US-amy\noutput_device: hw:CARD=Device\n")
    settings = AudioSettings()
    chosen_player = RecordingPlayer(device=resolve_output_device(settings.output_device))
    assert chosen_player.device == "hw:CARD=Device"


# --- AC-6 / FC-2 (schema), FC-12: speaking config loads, voice has no default -


def test_speaking_config_loads_via_shared_facility(tmp_path, monkeypatch):
    """`voice`, output device, and tagging keys load from `config/audio.yaml`
    through the shared facility into the surface's config; `voice` has **no
    default** (unset => absent, not a silent fallback). FC-12, and the FC-2
    no-default stance at the schema level."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    monkeypatch.setattr("hearth.config.CONFIG_DIR", config_dir)
    _clear_hearth_env(monkeypatch)

    from hearth.audio.config import AudioSettings

    (config_dir / "audio.yaml").write_text(
        "voice: en_US-amy-medium\n"
        "output_device: hw:CARD=Device\n"
        "presentation:\n"
        "  heard_color: '32'\n"
        "  spoken_color: '33'\n"
    )
    settings = AudioSettings()
    assert settings.voice == "en_US-amy-medium"
    assert settings.output_device == "hw:CARD=Device"
    assert settings.presentation.heard_color == "32"
    assert settings.presentation.spoken_color == "33"

    # `voice` has NO shipped default: an unset voice is representable as missing
    # (None) for FTHR-037 to turn into the first-run error -- not a silent voice.
    (config_dir / "audio.yaml").write_text("output_device: null\n")
    unset = AudioSettings()
    assert unset.voice is None
