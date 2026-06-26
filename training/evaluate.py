"""Quick sanity-eval for a trained wake-word .onnx.

Runs the model over a sample of held-out positive clips and a sample of
background-noise clips, and reports the peak score distribution for each. A
healthy model shows positives clustered near 1.0 and backgrounds near 0.0 with a
clear gap. This is a smoke check, not a formal ROC — the real false-positive
metric is the validation-set early-stopping target in wakeword.yml.

Usage (from repo root, via the training venv):
  training/.venv-train/bin/python training/evaluate.py \
      --model models/wake/hey_assistant.onnx \
      --positives training/work/hey_assistant/positive_test \
      --backgrounds training/data/audioset_16k
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from openwakeword.model import Model


def peak_scores(model: Model, key: str, clips: list[Path]) -> np.ndarray:
    scores = []
    for clip in clips:
        model.reset()
        preds = model.predict_clip(str(clip))
        scores.append(max(p[key] for p in preds))
    return np.array(scores)


def summarize(label: str, s: np.ndarray) -> None:
    def pct(q: float) -> float:
        return float(np.percentile(s, q))

    print(
        f"{label:<12} n={len(s):<5} "
        f"min={s.min():.3f} p10={pct(10):.3f} median={pct(50):.3f} "
        f"p90={pct(90):.3f} max={s.max():.3f} mean={s.mean():.3f}"
    )


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model", required=True)
    ap.add_argument("--positives", required=True)
    ap.add_argument("--backgrounds", required=True)
    ap.add_argument("--n", type=int, default=300, help="clips to sample per class")
    ap.add_argument("--threshold", type=float, default=0.5)
    ap.add_argument("--json", dest="json_path", default=None, help="write metrics here")
    ap.add_argument("--gate", action="store_true", help="exit 1 if below thresholds")
    ap.add_argument("--min-tp", type=float, default=0.90, help="gate: min true-positive rate")
    ap.add_argument("--max-fp", type=float, default=0.01, help="gate: max false-positive rate")
    ap.add_argument("--min-separation", type=float, default=0.0, help="gate: min pos p10 - bg p90")
    a = ap.parse_args()

    model = Model(wakeword_models=[a.model], inference_framework="onnx")
    key = list(model.models.keys())[0]
    print(f"model key: {key}\n")

    pos = sorted(Path(a.positives).glob("*.wav"))[: a.n]
    bg = sorted(Path(a.backgrounds).glob("*.wav"))[: a.n]

    p = peak_scores(model, key, pos)
    n = peak_scores(model, key, bg)

    summarize("positives", p)
    summarize("backgrounds", n)

    tp = float((p >= a.threshold).mean())
    fp = float((n >= a.threshold).mean())
    print(
        f"\n@threshold={a.threshold}: "
        f"true-positive rate={tp:.1%}, false-positive rate={fp:.1%}"
    )
    gap = float(np.percentile(p, 10) - np.percentile(n, 90))
    print(f"separation (pos p10 - bg p90) = {gap:+.3f}  ({'healthy' if gap > 0 else 'WEAK — overlap'})")

    passed = tp >= a.min_tp and fp <= a.max_fp and gap >= a.min_separation

    if a.json_path:
        def stats(s: np.ndarray) -> dict:
            return {
                "min": float(s.min()), "median": float(np.percentile(s, 50)),
                "max": float(s.max()), "mean": float(s.mean()),
            }

        metrics = {
            "model": a.model, "key": key, "threshold": a.threshold,
            "tp_rate": tp, "fp_rate": fp, "separation": gap, "passed": passed,
            "positives": stats(p), "backgrounds": stats(n),
        }
        Path(a.json_path).write_text(json.dumps(metrics, indent=2))

    if a.gate and not passed:
        print(
            f"\nGATE FAIL: need tp>={a.min_tp:.0%} (got {tp:.0%}), "
            f"fp<={a.max_fp:.0%} (got {fp:.0%}), separation>={a.min_separation:+.3f} (got {gap:+.3f})"
        )
        sys.exit(1)
