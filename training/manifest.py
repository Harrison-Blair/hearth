"""Registry for the trained wake-word series (models/wake/models.json).

The manifest indexes every committed model — its phrase and eval metrics — so you
can see what you've trained and select which series the runtime loads.

Subcommands (run from the repo root):
  upsert <slug> --phrase "X" --eval <eval.json>   # record one model (used by train_batch.sh)
  list                                            # show the trained series
  select <slug-or-phrase> [...]                   # load this series: writes config.yaml wake.model_paths

`select` also accepts a bare slug whose .onnx exists on disk but isn't in the
manifest yet. The env-var equivalent (no file edit) is:
  ASSISTANT_WAKE__MODEL_PATHS='["models/wake/a.onnx","models/wake/b.onnx"]'
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

MANIFEST = Path("models/wake/models.json")
CONFIG = Path("config.yaml")


def slug(phrase: str) -> str:
    """Phrase -> model name. Mirrors make_config.slug (kept inline so this module
    has no yaml dependency and runs under the assistant runtime venv)."""
    return re.sub(r"[^a-z0-9]+", "_", phrase.lower()).strip("_") or "wakeword"


def load() -> dict:
    return json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {}


def save(data: dict) -> None:
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def cmd_upsert(a: argparse.Namespace) -> None:
    m = load()
    ev = json.loads(Path(a.eval).read_text())
    m[a.slug] = {
        "phrase": a.phrase,
        "model_path": f"models/wake/{a.slug}.onnx",
        "tp_rate": ev["tp_rate"],
        "fp_rate": ev["fp_rate"],
        "separation": ev["separation"],
        "trained_at": datetime.now().isoformat(timespec="seconds"),
    }
    save(m)
    print(f"manifest: recorded {a.slug!r} ({a.phrase!r})")


def cmd_list(_a: argparse.Namespace) -> None:
    m = load()
    if not m:
        print("(no models trained yet)")
        return
    print(f"{'slug':<20} {'phrase':<22} {'tp':>6} {'fp':>6} {'sep':>7}")
    for k in sorted(m):
        e = m[k]
        print(
            f"{k:<20} {e['phrase']:<22} {e['tp_rate']:>6.1%} "
            f"{e['fp_rate']:>6.1%} {e['separation']:>+7.3f}"
        )


def _resolve(ref: str, m: dict) -> str:
    """A manifest slug, a manifest phrase, or a slug whose .onnx exists on disk."""
    if ref in m:
        return m[ref]["model_path"]
    for k, e in m.items():
        if e["phrase"] == ref:
            return e["model_path"]
    path = f"models/wake/{slug(ref)}.onnx"
    if Path(path).exists():
        return path
    raise SystemExit(f"error: no model for {ref!r} (not in manifest, {path} missing)")


def cmd_select(a: argparse.Namespace) -> None:
    m = load()
    paths = [_resolve(ref, m) for ref in a.refs]
    _write_model_paths(paths)
    # Verify the runtime will read exactly these.
    sys.path.insert(0, ".")
    from assistant.core.config import Config

    got = Config().wake.model_refs()
    assert got == paths, f"config.yaml write mismatch: {got} != {paths}"
    print("config.yaml wake.model_paths set to:")
    for p in paths:
        print(f"  - {p}")


def _write_model_paths(paths: list[str]) -> None:
    """Replace wake.model_paths in config.yaml, preserving comments/order."""
    lines = CONFIG.read_text().splitlines()
    start = next(i for i, ln in enumerate(lines) if ln.rstrip() == "wake:")
    # Block ends at the next top-level (unindented, non-comment) line.
    end = next(
        (i for i in range(start + 1, len(lines))
         if lines[i].strip() and not lines[i][0].isspace() and not lines[i].startswith("#")),
        len(lines),
    )
    block = lines[start + 1 : end]
    # Drop any existing model_paths: key and its "- " children (indent > 2).
    cleaned, skip = [], False
    for ln in block:
        if ln.lstrip().startswith("model_paths:"):
            skip = True
            continue
        if skip and (ln.strip().startswith("- ") or not ln.strip()):
            if not ln.strip():
                skip = False  # blank line ends the list
            continue
        skip = False
        cleaned.append(ln)
    new_block = ["  model_paths:"] + [f"    - {p}" for p in paths] + cleaned
    CONFIG.write_text("\n".join(lines[: start + 1] + new_block + lines[end:]) + "\n")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    up = sub.add_parser("upsert")
    up.add_argument("slug")
    up.add_argument("--phrase", required=True)
    up.add_argument("--eval", required=True, help="evaluate.py --json output")
    up.set_defaults(func=cmd_upsert)

    sub.add_parser("list").set_defaults(func=cmd_list)

    sel = sub.add_parser("select")
    sel.add_argument("refs", nargs="+", help="slugs and/or phrases to load")
    sel.set_defaults(func=cmd_select)

    args = ap.parse_args()
    args.func(args)
