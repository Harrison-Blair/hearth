#!/usr/bin/env python
"""Train a series of wake words sequentially on the livekit pipeline.

One phrase at a time (no parallelism). Reads phrases from training/phrases.txt (or
positional args), derives a per-phrase config from training/calcifer.yaml — dropping
its Calcifer-specific negatives so livekit auto-generates adversarials — and runs the
same flow as train.py per phrase, streaming each livekit run's stage output live under
a per-phrase header. A failing (or gate-failing) phrase is recorded and the batch
continues; the run ends with the manifest table.

  python training/train_batch.py                        # phrases from training/phrases.txt
  python training/train_batch.py "hey calcifer" athena  # phrases as positional args
  python training/train_batch.py --smoke                # fast tiny end-to-end per phrase
  python training/train_batch.py --n-samples 5000 --steps 20000   # reduced-scale sweep

Runs in .venv-train (see bootstrap.sh).
"""

from __future__ import annotations

import argparse
import copy
import subprocess
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import manifest  # noqa: E402  (training/ module, not the assistant package)
from train import REPO, apply_overrides, apply_smoke_overrides, run_training  # noqa: E402

BASE_CONFIG = REPO / "training" / "calcifer.yaml"
PHRASES_FILE = REPO / "training" / "phrases.txt"
# calcifer.yaml fields tuned for the Calcifer phrase specifically; they must not
# leak onto other phrases (livekit auto-generates their adversarial negatives).
PHRASE_SPECIFIC = ("custom_negative_phrases",)


def parse_phrases(text: str) -> list[str]:
    """One phrase per line; blank lines and #-comments (whole-line or trailing) ignored."""
    phrases = []
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            phrases.append(line)
    return phrases


def derive_config(base: dict, phrase: str) -> dict:
    """Per-phrase config from the base template: set model_name + target_phrases and
    drop the Calcifer-specific fields so nothing carries across phrases."""
    cfg = copy.deepcopy(base)
    cfg["model_name"] = manifest.slug(phrase)
    cfg["target_phrases"] = [phrase]
    for key in PHRASE_SPECIFIC:
        cfg.pop(key, None)
    return cfg


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("phrases", nargs="*", help="phrases to train (default: training/phrases.txt)")
    ap.add_argument("--smoke", action="store_true", help="fast tiny end-to-end run per phrase")
    ap.add_argument("--n-samples", type=int, default=None, help="override n_samples (sweeps)")
    ap.add_argument("--steps", type=int, default=None, help="override training steps (sweeps)")
    ap.add_argument("--skip-setup", action="store_true", help="skip data download for every phrase")
    a = ap.parse_args()

    phrases = a.phrases or parse_phrases(PHRASES_FILE.read_text())
    if not phrases:
        raise SystemExit(f"no phrases (pass as args or fill {PHRASES_FILE.relative_to(REPO)})")

    base = yaml.safe_load(BASE_CONFIG.read_text())
    n = len(phrases)
    failures: list[str] = []
    for i, phrase in enumerate(phrases):
        cfg = derive_config(base, phrase)
        if a.smoke:
            apply_smoke_overrides(cfg)
        apply_overrides(cfg, n_samples=a.n_samples, steps=a.steps)
        print(f"\n{'=' * 70}\n[{i + 1}/{n}] {phrase}  (model {cfg['model_name']})\n{'=' * 70}",
              flush=True)
        try:
            # Only the first phrase downloads data; the rest reuse it.
            run_training(cfg, skip_setup=(a.skip_setup or i > 0))
        except subprocess.CalledProcessError as exc:
            print(f"[{i + 1}/{n}] {phrase}: FAILED — {exc}", flush=True)
            failures.append(phrase)

    print(f"\n{'=' * 70}\nBatch summary\n{'=' * 70}", flush=True)
    print(f"{n - len(failures)}/{n} phrases trained; "
          f"failures: {', '.join(failures) or 'none'}\n", flush=True)
    subprocess.run([sys.executable, str(REPO / "training" / "manifest.py"), "list"], cwd=REPO)
    if failures:
        sys.exit(1)


if __name__ == "__main__":
    main()
