"""Derive human-readable wake phrases from the loaded wake-word models.

The wake phrase shown in logs and the TUI is *derived* from the model(s) the
detector loads, never hand-maintained — so it can't drift from what actually
wakes the assistant. The trained-model manifest (``models/wake/models.json``,
written by ``training/manifest.py``) is the authoritative phrase source; any model
not recorded there falls back to prettifying its filename stem.

The stem rule is the inverse of ``manifest.slug``: model files are named with the
phrase lowercased and spaces replaced by underscores (``hey_assistant.onnx`` <-
"hey assistant"), so ``stem.replace("_", " ")`` recovers it.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

MANIFEST = Path("models/wake/models.json")


def load_manifest() -> dict:
    """The trained-model registry, or ``{}`` if it hasn't been written yet."""
    return json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {}


def prettify(stem: str) -> str:
    """Model filename stem -> phrase. Inverse of ``manifest.slug``: drop a trailing
    version suffix (e.g. ``_v0.1`` on stock models) and turn underscores into spaces."""
    return re.sub(r"_v\d+(\.\d+)*$", "", stem).replace("_", " ")


def phrase_for(ref: str, manifest: dict | None = None) -> str:
    """The phrase a single model ref wakes on: its manifest entry if recorded,
    else the prettified filename stem. ``ref`` may be a path or a bare stock name."""
    if manifest is None:
        manifest = load_manifest()
    stem = Path(ref).stem
    for key, entry in manifest.items():
        if key == stem or Path(entry.get("model_path", "")).stem == stem:
            return entry["phrase"]
    return prettify(stem)


def phrases_for(refs: list[str]) -> list[str]:
    """The acceptable phrases for a set of loaded models, order-preserving, de-duped."""
    manifest = load_manifest()
    seen: dict[str, None] = {}
    for ref in refs:
        seen.setdefault(phrase_for(ref, manifest), None)
    return list(seen)
