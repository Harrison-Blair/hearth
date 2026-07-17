"""First-run voice acquisition tests (FTHR-037).

Exercise the *startup voice check* the audio surface performs before serving:
resolve the configured voice, fetch it if absent, or emit the absent-voice
first-run error and exit as a configuration problem. All proven **offline** with
an injected fetcher double -- no network, no real download. The real download and
whether the message reads well are confirmed at the first real run / FTHR-039
(this suite pins the policy and the message *content*, not the prose quality).
"""
from __future__ import annotations

import inspect

import pytest


class RecordingFetcher:
    """An injected fetch seam that records every call instead of downloading --
    the hermetic double that lets CI prove the fetch *policy* with no network."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def __call__(self, voice: str, dest) -> None:
        self.calls.append((voice, dest))
        # A real fetcher would materialise the artifact; the policy tests only
        # need to know *whether* it was called, so this stays a pure recorder.


# --- AC-2 / FC-2, FC-3: absent voice => actionable first-run error, no crash --


def test_absent_voice_refuses_to_start_with_actionable_message(tmp_path):
    """With **no voice configured**, the startup check refuses to start: it
    raises `SystemExit` (non-zero, no traceback) whose message **names the
    config setting** and **states how to discover valid voices**. A vague
    "voice not found" must not pass -- both fragments are asserted. The fetcher
    is never called (there is nothing named to fetch)."""
    from hearth.audio.voice import ensure_voice

    fetch = RecordingFetcher()
    with pytest.raises(SystemExit) as excinfo:
        ensure_voice(None, voices_dir=tmp_path, fetch=fetch)

    exc = excinfo.value
    # Exits as a configuration problem: a SystemExit carrying a message string,
    # which the interpreter prints to stderr and exits non-zero WITHOUT a
    # traceback (the manifest.py `error:`/SystemExit idiom). The code is the
    # message, not 0/None.
    assert isinstance(exc, SystemExit)
    assert exc.code not in (0, None)
    message = str(exc.code)
    # Fragment 1 -- names the exact setting by its real path in config/audio.yaml.
    assert "voice" in message
    assert "config/audio.yaml" in message
    # Fragment 2 -- states how to discover valid voices (a pointer, not a command).
    assert "https://" in message
    assert "piper" in message.lower()
    # Nothing was fetched: there was no named voice to acquire.
    assert fetch.calls == []


# --- AC-3 / FC-4: named-but-absent voice is fetched before serving -----------


def test_configured_absent_voice_is_fetched_before_serving(tmp_path):
    """A **named-but-absent** voice triggers the injected fetcher, targeting the
    on-disk artifact the renderer will load, and `ensure_voice` returns that
    path -- the acquisition completes as a startup precondition, before serving
    begins. FC-4."""
    from hearth.audio.voice import ensure_voice, voice_artifact

    fetch = RecordingFetcher()
    artifact = ensure_voice("en_US-amy-medium", voices_dir=tmp_path, fetch=fetch)

    expected = voice_artifact("en_US-amy-medium", voices_dir=tmp_path)
    assert artifact == expected
    # The fetcher fired exactly once, for this voice, at the artifact path.
    assert fetch.calls == [("en_US-amy-medium", expected)]


# --- AC-3 / FC-4: an already-present voice is NOT re-fetched ------------------


def test_present_voice_is_not_refetched(tmp_path):
    """A **named-and-present** voice does **not** invoke the fetcher -- a naive
    always-fetch fails here. FC-4, the other half of the branch."""
    from hearth.audio.voice import ensure_voice, voice_artifact

    artifact = voice_artifact("en_US-amy-medium", voices_dir=tmp_path)
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_bytes(b"present")  # the voice already exists on disk

    fetch = RecordingFetcher()
    resolved = ensure_voice("en_US-amy-medium", voices_dir=tmp_path, fetch=fetch)

    assert resolved == artifact
    # Present => no fetch.
    assert fetch.calls == []


# --- AC-4 / FC-11: the fetch path is hermetic and injectable ------------------


def test_fetch_is_hermetic_and_injectable(tmp_path, monkeypatch):
    """The fetch is driven entirely by the injected seam: with sockets fused to
    raise, `ensure_voice` still resolves both the fetch (absent) and no-fetch
    (present) branches -- proving the policy performs **no network access** of
    its own. Guards against a real download creeping into the policy path."""
    import socket

    def no_network(*args, **kwargs):  # pragma: no cover - only fires on regression
        raise AssertionError("ensure_voice performed network access")

    monkeypatch.setattr(socket, "socket", no_network)

    from hearth.audio.voice import ensure_voice, voice_artifact

    # Absent branch: fetch is the injected recorder, so no socket is opened.
    fetch = RecordingFetcher()
    ensure_voice("en_US-amy-medium", voices_dir=tmp_path, fetch=fetch)
    assert fetch.calls == [("en_US-amy-medium", voice_artifact("en_US-amy-medium", voices_dir=tmp_path))]

    # Present branch: no fetch attempted, still no network.
    artifact = voice_artifact("en_US-amy-medium", voices_dir=tmp_path)
    artifact.write_bytes(b"present")
    fetch2 = RecordingFetcher()
    ensure_voice("en_US-amy-medium", voices_dir=tmp_path, fetch=fetch2)
    assert fetch2.calls == []


# --- AC-2 ordering: an unset voice exits BEFORE the surface serves -----------


def test_unset_voice_exits_before_serving(tmp_path, monkeypatch):
    """The surface entry point runs the voice check as a precondition: an unset
    voice raises `SystemExit` before any serving is attempted -- the injected
    `serve` seam is never called. Makes the "check -> serve, or error -> exit"
    ordering observable at the surface boundary."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    monkeypatch.setattr("hearth.config.CONFIG_DIR", config_dir)
    for key in list(__import__("os").environ):
        if key.startswith("HEARTH_"):
            monkeypatch.delenv(key, raising=False)
    (config_dir / "audio.yaml").write_text("voice: null\n")

    from hearth.audio.surface import main

    served: list[bool] = []
    fetch = RecordingFetcher()
    with pytest.raises(SystemExit):
        main(fetch=fetch, voices_dir=tmp_path, serve=lambda: served.append(True))

    # Never served, never fetched: the unset voice stopped startup first.
    assert served == []
    assert fetch.calls == []


# --- AC-5 / Out of Scope: no voice-listing subcommand is introduced ----------


def test_no_voice_listing_subcommand_is_added():
    """Discovery is a **pointer in the message only** -- no `--list-voices`,
    voice-audition, or picker command/flag is added to the surface. The user
    drew this line explicitly (PLM-009 Q3 / Out of Scope); this guards it so a
    later "helpful" addition is caught."""
    import pkgutil

    import hearth.audio

    forbidden = ("list-voices", "list_voices", "--voices", "audition", "picker")
    for module in pkgutil.iter_modules(hearth.audio.__path__):
        source = inspect.getsource(
            __import__(f"hearth.audio.{module.name}", fromlist=["_"])
        )
        lowered = source.lower()
        for token in forbidden:
            assert token not in lowered, f"{module.name} introduces {token!r}"

    # The entry point takes no CLI subcommand/positional: only injected,
    # keyword-only seams (for tests) with defaults.
    from hearth.audio.surface import main

    for param in inspect.signature(main).parameters.values():
        assert param.kind == inspect.Parameter.KEYWORD_ONLY
