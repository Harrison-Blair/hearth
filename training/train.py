#!/usr/bin/env python
"""Train the "Calcifer" wake-word model via the livekit-wakeword CLI.

Runs in .venv-train (torch + livekit-wakeword[train,eval,export]; see bootstrap.sh).
Loads training/calcifer.yaml, optionally shrinks it for a fast --smoke plumbing run,
runs livekit's setup + full pipeline (generate -> augment -> train -> export -> eval),
installs the exported .onnx into models/wake/, and records it in the manifest.

  python training/train.py                 # full production run
  python training/train.py --smoke         # tiny end-to-end run, proves the plumbing
  python training/train.py --skip-setup    # reuse already-downloaded data/features

``run_training`` is the reusable per-model flow; train_batch.py imports it.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
WORK = REPO / "training" / "work"


def apply_smoke_overrides(cfg: dict) -> None:
    """Shrink a prod config to a fast end-to-end plumbing run. The ``_smoke`` suffix
    on model_name is load-bearing: tui.discovery.clean_smoke_models keys on it."""
    cfg["model_name"] = f"{cfg['model_name']}_smoke"
    cfg["n_samples"] = 200
    cfg["n_samples_val"] = 50
    cfg["n_background_samples"] = 50
    cfg["n_background_samples_val"] = 10
    cfg["steps"] = 500
    cfg["tts_batch_size"] = 50


def apply_overrides(cfg: dict, *, n_samples: int | None = None, steps: int | None = None) -> None:
    """Optional reduced-scale overrides for cheap sweeps. n_samples scales the
    validation count with it (keeping the prod ~5:1 train:val ratio)."""
    if n_samples is not None:
        cfg["n_samples"] = n_samples
        cfg["n_samples_val"] = max(1, n_samples // 5)
    if steps is not None:
        cfg["steps"] = steps


def load_config(
    config_path: str | Path,
    *,
    smoke: bool = False,
    n_samples: int | None = None,
    steps: int | None = None,
) -> dict:
    cfg = yaml.safe_load(Path(config_path).read_text())
    if smoke:
        apply_smoke_overrides(cfg)
    apply_overrides(cfg, n_samples=n_samples, steps=steps)
    return cfg


def _livekit(*args: str) -> None:
    # MIOpen's default per-shape kernel search cripples VITS synthesis on ROCm
    # (variable-length inputs = endless re-tuning); FAST picks heuristically.
    # setdefault so the environment can still override.
    os.environ.setdefault("MIOPEN_FIND_MODE", "FAST")
    os.environ.setdefault("MIOPEN_LOG_LEVEL", "3")  # errors only, no workspace spam
    # VITS's variable-length clips make the HIP caching allocator accumulate
    # blocks until OOM (~14 GB held mid-generate on the 16 GB card); GC reclaims
    # cache under pressure and the split cap limits fragmentation. Note:
    # expandable_segments is NOT supported on ROCm builds — don't use it.
    os.environ.setdefault(
        "PYTORCH_CUDA_ALLOC_CONF", "garbage_collection_threshold:0.8,max_split_size_mb:512"
    )
    # Invoke via the module (this interpreter = .venv-train) so we don't depend on
    # the console script being on PATH. Inherits stdio, so stage output streams live.
    subprocess.run([sys.executable, "-m", "livekit.wakeword", *args], cwd=REPO, check=True)


def clear_run(cfg: dict, *, clips: bool = False) -> None:
    """Delete a model's previous run artifacts so training starts from scratch.

    Keeps the synthesized clip dirs (the multi-hour part; livekit resumes from
    them) unless clips=True, which wipes the whole model output dir.
    """
    out = REPO / cfg["output_dir"] / cfg["model_name"]
    if not out.exists():
        return
    if clips:
        shutil.rmtree(out)
        print(f"cleared {out.relative_to(REPO)} (including synthesized clips)")
        return
    for entry in out.iterdir():
        if entry.is_dir() and any(entry.glob("clip_*.wav")):
            continue
        shutil.rmtree(entry) if entry.is_dir() else entry.unlink()
    print(f"cleared derived artifacts in {out.relative_to(REPO)} (clips kept)")


def run_training(cfg: dict, *, skip_setup: bool = False) -> None:
    """Write cfg to training/work/, run livekit setup + full pipeline, install the
    exported .onnx into models/wake/, and record it in the manifest. Raises
    subprocess.CalledProcessError if a livekit stage fails."""
    name = cfg["model_name"]
    WORK.mkdir(parents=True, exist_ok=True)
    effective = WORK / f"{name}.yaml"
    effective.write_text(yaml.safe_dump(cfg, sort_keys=False))
    print(f"effective config -> {effective.relative_to(REPO)}")

    if not skip_setup:
        _livekit("setup", "--config", str(effective))
    _livekit("run", str(effective))

    exported = REPO / cfg["output_dir"] / name / f"{name}.onnx"
    dest = REPO / "models" / "wake" / f"{name}.onnx"
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(exported, dest)
    print(f"installed {dest.relative_to(REPO)}")

    eval_json = REPO / cfg["output_dir"] / name / f"{name}_eval.json"
    phrase = cfg["target_phrases"][0].title()
    subprocess.run(
        [sys.executable, str(REPO / "training" / "manifest.py"), "upsert", name,
         "--phrase", phrase, "--eval", str(eval_json),
         "--target-fpph", str(cfg["target_fp_per_hour"])],
        cwd=REPO, check=True,
    )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", default=str(REPO / "training" / "calcifer.yaml"))
    ap.add_argument("--smoke", action="store_true", help="fast tiny end-to-end run")
    ap.add_argument("--skip-setup", action="store_true", help="skip the multi-GB data download")
    ap.add_argument("--n-samples", type=int, default=None, help="override n_samples (sweeps)")
    ap.add_argument("--steps", type=int, default=None, help="override training steps (sweeps)")
    ap.add_argument("--fresh", action="store_true",
                    help="clear previous run artifacts (features/checkpoints/eval) before "
                         "training; keeps synthesized clips. Don't use while a run is live.")
    ap.add_argument("--fresh-clips", action="store_true",
                    help="like --fresh but also deletes synthesized clips (full regeneration)")
    a = ap.parse_args()

    cfg = load_config(a.config, smoke=a.smoke, n_samples=a.n_samples, steps=a.steps)
    if a.fresh or a.fresh_clips:
        clear_run(cfg, clips=a.fresh_clips)
    run_training(cfg, skip_setup=a.skip_setup)
    print(f"done: models/wake/{cfg['model_name']}.onnx"
          f"  (manifest updated; `python training/manifest.py list`)")


if __name__ == "__main__":
    main()
