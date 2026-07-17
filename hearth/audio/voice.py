"""First-run voice acquisition (FTHR-037): the startup voice check.

The audio surface performs one check before it serves: resolve the configured
voice, **fetch it if absent**, or emit the **absent-voice first-run error** and
exit as a *configuration problem*. This is the load-bearing first-run UX of the
speaking plumage -- a user who has not named a voice meets this feather's error;
a user who has named one pays only one config line and a first run, not a setup
ritual.

Boundaries: this consumes FTHR-035's `voice` config key (unset ⇒ absent); it does
**not** redefine that key, render (FTHR-036), or play (FTHR-038). The fetch runs
behind an **injectable seam** so CI proves the policy -- fetch when absent, skip
when present -- with no network. The real download from a real source is deferred
to the first real run / FTHR-039 (see `download_voice`).
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

# Where piper voice artifacts live on disk. A module constant, mirroring
# `training/manifest.py`'s hardcoded model paths -- deliberately NOT a config
# field, so this feather does not touch FTHR-035's `voice` schema. The configured
# `voice` is a NAME; its artifact is `<name>.onnx` under this directory, which is
# what FTHR-036's `Renderer` loads.
VOICES_DIR = Path("models/voices")

# A fetch seam: given a voice name and its destination artifact path, acquire it.
# Injected so CI drives it with a recorder double (no network); production wires
# `download_voice`.
Fetcher = Callable[[str, Path], None]


def voice_artifact(voice: str, *, voices_dir: Path = VOICES_DIR) -> Path:
    """Resolve a configured voice **name** to the on-disk piper artifact the
    renderer (FTHR-036) loads. Name -> `<voices_dir>/<name>.onnx`."""
    return voices_dir / f"{voice}.onnx"


def _absent_voice_error() -> SystemExit:
    """The absent-voice first-run message: names the setting and points at where
    voices come from, as a `SystemExit` so it prints to stderr and exits non-zero
    **without a traceback** (the `training/manifest.py` `error:`/SystemExit idiom).
    It reads as an instruction -- "set this, here's where voices come from" -- not
    a crash. The pointer is a *pointer*, never a command that browses or previews."""
    return SystemExit(
        "error: no TTS voice is configured. hearth ships no default voice, so a "
        "voice must be named before the audio surface can speak.\n"
        "  Set `voice` in config/audio.yaml to a piper voice name, e.g. "
        "`voice: en_US-amy-medium`.\n"
        "  Voices come from the piper voice catalog -- browse names at "
        "https://github.com/rhasspy/piper/blob/master/VOICES.md and copy one in. "
        "hearth fetches the named voice on the next run."
    )


def download_voice(voice: str, dest: Path) -> None:  # pragma: no cover - deferred
    """Production fetch seam -- **deferred to the first real run / FTHR-039**.

    The startup *policy* (check ⇒ fetch-if-absent ⇒ serve, or error ⇒ exit) and
    the message content are proven offline in this feather via an injected fetcher
    (PLM-009 FC-11; molt AC-4). The real network download from a real source is
    exercised only when a human runs the first-run step, confirmed in FTHR-039's
    smoke; wiring a real source here would be an un-provable, out-of-scope network
    dependency (spec AC-7). Until then, a named-but-absent voice surfaces as an
    actionable instruction rather than a silent no-op."""
    raise SystemExit(
        f"error: voice {voice!r} is configured but not present at {dest}, and "
        "automatic voice download is not yet available. Acquire the piper voice "
        "manually (a `.onnx` + `.onnx.json` pair from "
        "https://github.com/rhasspy/piper/blob/master/VOICES.md) and place it at "
        f"{dest.parent}/. Automatic first-run acquisition lands in FTHR-039."
    )


def ensure_voice(
    voice: Optional[str],
    *,
    voices_dir: Path = VOICES_DIR,
    fetch: Fetcher = download_voice,
) -> Path:
    """The startup voice check, in one place. Returns the resolved on-disk
    artifact once it is present; raises `SystemExit` when no voice is configured.

    - `voice` unset (`None`/empty): raise the absent-voice first-run error and
      exit (non-zero, no traceback) -- a configuration problem, not a crash.
    - `voice` named but the artifact is absent: `fetch` it (before serving), then
      return its path.
    - `voice` named and present: return its path, **no** fetch.

    The fetch is the injected seam, so this whole check is offline in CI."""
    if not voice:
        raise _absent_voice_error()
    artifact = voice_artifact(voice, voices_dir=voices_dir)
    if not artifact.exists():
        fetch(voice, artifact)
    return artifact
