"""Stamp a training config for a given wake phrase from training/wakeword.yml.

Overrides only the phrase-specific fields (target_phrase, model_name) so all
shared tuning stays in one place. `--smoke` shrinks the sample/step counts for a
fast end-to-end validation run and suffixes the model name so it can't clobber a
full model. Prints the path of the written config (for train.sh to consume).
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import yaml

BASE = Path("training/wakeword.yml")


def slug(phrase: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", phrase.lower()).strip("_") or "wakeword"


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--phrase", default=None, help="wake phrase (default: base config's)")
    ap.add_argument("--name", default=None, help="model name (default: slug of phrase)")
    ap.add_argument("--smoke", action="store_true", help="tiny fast validation run")
    ap.add_argument("--out", default=None, help="output path (default: training/work/<name>.yml)")
    a = ap.parse_args()

    cfg = yaml.safe_load(BASE.read_text())
    phrase = a.phrase or cfg["target_phrase"][0]
    name = a.name or slug(phrase)
    cfg["target_phrase"] = [phrase]
    if a.smoke:
        name = f"{name}_smoke"
        cfg["n_samples"] = 2000
        cfg["n_samples_val"] = 500
        cfg["steps"] = 20000
    cfg["model_name"] = name

    out = Path(a.out or f"training/work/{name}.yml")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(yaml.safe_dump(cfg, sort_keys=False))
    print(out)
