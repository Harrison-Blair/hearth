"""Registry for the trained wake-word series (models/wake/models.json).

The manifest indexes every trained model — its phrase and eval metrics — so you
can see what you've trained and select which series the runtime loads.

Subcommands (run from the repo root):
  upsert <slug> --phrase "X" --eval <eval.json>   # record one model (used by train.py)
  list                                            # show the trained series
  regen                                           # rebuild manifest from models/wake/*.onnx on disk
  remove <slug>                                   # drop one manifest entry (no-op if absent)
  select <slug-or-phrase> [...]                   # load these models: writes
                                                  # config/audio.yaml wake_models

`select` writes each chosen model's path *and* its threshold (the operating point
recorded in models.json) into the audio surface's `wake_models` list, since each
model triggers on its own threshold. A bare slug whose .onnx exists on disk but
isn't in the manifest can't supply a threshold, so record it with `upsert` first.

This module is deliberately standalone: stdlib only, no import of the hearth
runtime package, so training has no effect on the rest of the tree.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path

MANIFEST = Path("models/wake/models.json")
CONFIG = Path("config/audio.yaml")


def slug(phrase: str) -> str:
    """Phrase -> model name: lowercase, non-alphanumerics collapsed to underscores."""
    return re.sub(r"[^a-z0-9]+", "_", phrase.lower()).strip("_") or "wakeword"


def prettify(stem: str) -> str:
    """Model slug -> display phrase: underscores to spaces, title-cased. The display
    inverse of slug(); lossy (original casing/punctuation is not recovered), which is
    fine because the phrase is only metadata in models.json."""
    return re.sub(r"_+", " ", stem).strip().title() or stem


def load() -> dict:
    return json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {}


def save(data: dict) -> None:
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def cmd_upsert(a: argparse.Namespace) -> None:
    m = load()
    # livekit's <model>_eval.json: report the operating point its find_best_threshold
    # picked (max recall subject to the FPPH target), which is the threshold the
    # runtime should wake on. gate_passed = did that point actually meet the target.
    ev = json.loads(Path(a.eval).read_text())
    m[a.slug] = {
        "phrase": a.phrase,
        "model_path": f"models/wake/{a.slug}.onnx",
        "fpph": ev["optimal_fpph"],
        "recall": ev["optimal_recall"],
        "threshold": ev["optimal_threshold"],
        "gate_passed": ev["optimal_fpph"] <= a.target_fpph,
        "trained_at": datetime.now().isoformat(timespec="seconds"),
    }
    save(m)
    print(f"manifest: recorded {a.slug!r} ({a.phrase!r})")


def cmd_list(_a: argparse.Namespace) -> None:
    m = load()
    if not m:
        print("(no models trained yet)")
        return
    print(f"{'slug':<20} {'phrase':<22} {'recall':>7} {'fpph':>7} {'thr':>6}")
    for k in sorted(m):
        e = m[k]
        # regen'd (untrained) entries carry no eval metrics yet.
        recall = f"{e['recall']:>7.1%}" if "recall" in e else f"{'—':>7}"
        fpph = f"{e['fpph']:>7.2f}" if "fpph" in e else f"{'—':>7}"
        thr = f"{e['threshold']:>6.2f}" if "threshold" in e else f"{'—':>6}"
        gate = " ✗gate" if e.get("gate_passed") is False else ""
        print(f"{k:<20} {e['phrase']:<22} {recall} {fpph} {thr}{gate}")


def cmd_regen(_a: argparse.Namespace) -> None:
    """Backfill a manifest entry for every models/wake/*.onnx that isn't recorded
    yet, deriving its phrase from the filename. Existing entries (with eval metrics)
    are left untouched, so the manifest is reproducible if models.json is lost."""
    m = load()
    added = []
    for path in sorted(Path("models/wake").glob("*.onnx")):
        stem = path.stem
        if stem in m:
            continue
        m[stem] = {"phrase": prettify(stem), "model_path": f"models/wake/{stem}.onnx"}
        added.append(stem)
    save(m)
    print(f"manifest: added {len(added)} model(s)" + (f": {', '.join(added)}" if added else ""))


def cmd_remove(a: argparse.Namespace) -> None:
    m = load()
    existed = a.slug in m
    m.pop(a.slug, None)
    save(m)
    print(f"manifest: removed {a.slug!r}" if existed else f"manifest: {a.slug!r} not found")


def _resolve(ref: str, m: dict) -> tuple[str, float]:
    """Resolve a ref to (model_path, threshold). A manifest slug or a manifest
    phrase; the threshold is the model's operating point recorded in models.json.
    A bare slug whose .onnx exists on disk but isn't in the manifest has no
    threshold to write, so it is a clear error rather than a silent default."""
    entry = m.get(ref)
    if entry is None:
        entry = next((e for e in m.values() if e.get("phrase") == ref), None)
    if entry is None:
        path = f"models/wake/{slug(ref)}.onnx"
        if not Path(path).exists():
            raise SystemExit(f"error: no model for {ref!r} (not in manifest, {path} missing)")
        raise SystemExit(
            f"error: {ref!r} has an .onnx on disk but no {MANIFEST} entry, so no "
            f"threshold to write. Record it first: "
            f"python training/manifest.py upsert {slug(ref)} --phrase ... --eval <eval.json>"
        )
    if "threshold" not in entry:
        raise SystemExit(
            f"error: {ref!r} has no threshold in {MANIFEST} (regen'd entry?). "
            f"Record its eval with 'upsert' before selecting."
        )
    return entry["model_path"], entry["threshold"]


def cmd_select(a: argparse.Namespace) -> None:
    m = load()
    models = [_resolve(ref, m) for ref in a.refs]
    _write_wake_models(models)
    # Verify the write round-trips (catches _write_wake_models bugs). Read it back
    # ourselves rather than importing the runtime, so training stays standalone.
    got = _read_wake_models()
    assert got == models, f"{CONFIG} write mismatch: {got} != {models}"
    print(f"{CONFIG} wake_models set to:")
    for path, threshold in models:
        print(f"  - {path} (threshold {threshold})")


def _wake_models_start(lines: list[str]) -> int:
    """Index of the top-level `wake_models:` key. When absent, emit a clear,
    actionable error naming the section and file -- never a bare StopIteration."""
    for i, ln in enumerate(lines):
        if ln.rstrip() == "wake_models:":
            return i
    raise SystemExit(
        f"error: no 'wake_models:' section in {CONFIG}. Create it by copying "
        f"config/defaults/audio.yaml to {CONFIG}, then re-run select."
    )


def _write_wake_models(models: list[tuple[str, float]]) -> None:
    """Replace the wake_models list in config/audio.yaml with {path, threshold}
    entries, preserving the surrounding sections and any comments/blank lines."""
    lines = CONFIG.read_text().splitlines()
    start = _wake_models_start(lines)
    # Block ends at the next top-level (unindented, non-comment) line.
    end = next(
        (i for i in range(start + 1, len(lines))
         if lines[i].strip() and not lines[i][0].isspace() and not lines[i].startswith("#")),
        len(lines),
    )
    # The block holds only the list; keep comments/blank lines, drop old entries.
    kept = [ln for ln in lines[start + 1 : end] if not ln.strip() or ln.lstrip().startswith("#")]
    entries = []
    for path, threshold in models:
        entries.append(f"  - path: {path}")
        entries.append(f"    threshold: {threshold}")
    new_block = entries + kept
    CONFIG.write_text("\n".join(lines[: start + 1] + new_block + lines[end:]) + "\n")


def _read_wake_models() -> list[tuple[str, float]]:
    """Read the wake_models list back out of config/audio.yaml (stdlib only,
    symmetric with _write_wake_models) so select can verify its own write without
    importing the runtime."""
    lines = CONFIG.read_text().splitlines()
    start = _wake_models_start(lines)
    models: list[list] = []
    for ln in lines[start + 1:]:
        if ln.strip() and not ln[0].isspace() and not ln.startswith("#"):
            break  # next top-level section ends the wake_models block
        s = ln.strip()
        if s.startswith("- path:"):
            models.append([s.split(":", 1)[1].strip(), None])
        elif s.startswith("threshold:") and models:
            models[-1][1] = float(s.split(":", 1)[1].strip())
    return [(path, threshold) for path, threshold in models]


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    up = sub.add_parser("upsert")
    up.add_argument("slug")
    up.add_argument("--phrase", required=True)
    up.add_argument("--eval", required=True, help="livekit <model>_eval.json")
    up.add_argument("--target-fpph", type=float, default=0.1,
                    help="FPPH gate: gate_passed = optimal_fpph <= this")
    up.set_defaults(func=cmd_upsert)

    sub.add_parser("list").set_defaults(func=cmd_list)
    sub.add_parser("regen").set_defaults(func=cmd_regen)

    rm = sub.add_parser("remove")
    rm.add_argument("slug")
    rm.set_defaults(func=cmd_remove)

    sel = sub.add_parser("select")
    sel.add_argument("refs", nargs="+", help="slugs and/or phrases to load")
    sel.set_defaults(func=cmd_select)

    args = ap.parse_args()
    args.func(args)
