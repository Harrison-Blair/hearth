"""Parallel Stage-1 clip synthesizer for openWakeWord training (CPU speed-up).

`openwakeword.train --generate_clips` synthesizes the four clip sets
(positive/negative x train/test) sequentially in one process — the multi-hour
"long pole" of a run. It also *skips* any set whose output dir is already ~full
(its `len(os.listdir(dir)) <= 0.95*n_samples` resume guard). This script pre-fills
those dirs using N thread-pinned worker processes, so the subsequent
`openwakeword.train` run finds the clips, logs "Skipping generation...", and jumps
straight to augment + features + train.

The per-set synthesis params (texts, batch sizes, noise/length scales) are copied
verbatim from openwakeword/train.py, and the total clip counts are unchanged, so
the trained model is equivalent — this is a pure parallelism win, not a quality
trade-off.

Two modes, one file:
  orchestrator: python synth_clips.py --config CFG --jobs N [--cores B]
  worker:       python synth_clips.py --worker --config CFG --set SET --count K \
                       --threads T [--with-custom]

torch must see OMP_NUM_THREADS before it is imported, so the orchestrator sets it
in each worker's environment and workers import torch lazily.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

import yaml

from ui import console  # shared rich console (degrades to plain when not a tty)

# The four clip sets openWakeWord generates, in the order train.py emits them.
# `count`: which config field drives the clip count. `noise`: noise_scales and
# noise_scale_ws value (train sets use 0.98, test sets 1.0). `neg`: adversarial
# (negative) set — text comes from generate_adversarial_texts, smaller batch.
SETS = {
    "positive_train": {"count": "n_samples", "noise": 0.98, "neg": False},
    "positive_test": {"count": "n_samples_val", "noise": 1.0, "neg": False},
    "negative_train": {"count": "n_samples", "noise": 0.98, "neg": True},
    "negative_test": {"count": "n_samples_val", "noise": 1.0, "neg": True},
}

MIN_CHUNK = 256  # don't spin a whole worker (a VITS model load) for fewer clips


def set_dir(cfg: dict, set_name: str) -> str:
    return os.path.join(cfg["output_dir"], cfg["model_name"], set_name)


def count_wavs(d: str) -> int:
    try:
        return sum(1 for e in os.scandir(d) if e.name.endswith(".wav"))
    except FileNotFoundError:
        return 0


def split_evenly(total: int, parts: int) -> list[int]:
    """Divide `total` into `parts` chunks, remainder spread over the first ones."""
    base, rem = divmod(total, parts)
    return [base + (1 if i < rem else 0) for i in range(parts)]


# --------------------------------------------------------------------------- #
# Worker: synthesize one set's share of clips in a thread-pinned subprocess.
# --------------------------------------------------------------------------- #
def run_worker(cfg: dict, set_name: str, count: int, threads: int, with_custom: bool) -> None:
    import logging
    import warnings

    warnings.filterwarnings("ignore")  # torchaudio "kaiser_window" deprecation et al.
    os.environ["OMP_NUM_THREADS"] = str(threads)  # parent set this too; reassert
    import torch  # imported here, after OMP_NUM_THREADS, so the pool binds to `threads`

    torch.set_num_threads(threads)

    sys.path.insert(0, cfg["piper_sample_generator_path"])
    from generate_samples import generate_samples  # noqa: E402  (lazy, needs sys.path)

    # generate_samples logs a per-batch DEBUG line per worker; with --stream that's
    # a flood. The orchestrator's aggregate Stage-1 line covers progress, so keep
    # workers at WARNING (real failures still surface).
    logging.getLogger("generate_samples").setLevel(logging.WARNING)

    spec = SETS[set_name]
    phrases = cfg["target_phrase"]
    if spec["neg"]:
        from openwakeword.data import generate_adversarial_texts  # noqa: E402

        # custom_negative_phrases belong to one worker only (worker 0) so they
        # aren't over-represented P-fold across the fan-out.
        text: list[str] = list(cfg.get("custom_negative_phrases") or []) if with_custom else []
        per = max(1, count // len(phrases))
        for phrase in phrases:
            text.extend(
                generate_adversarial_texts(
                    input_text=phrase,
                    N=per,
                    include_partial_phrase=1.0,
                    include_input_words=0.2,
                )
            )
        batch_size = max(1, cfg["tts_batch_size"] // 7)
    else:
        text = list(phrases)
        batch_size = cfg["tts_batch_size"]

    # UUID names everywhere (train.py only does this for the train sets) so clips
    # from different workers never collide; augment_clips just globs *.wav.
    file_names = [uuid.uuid4().hex + ".wav" for _ in range(count)]
    generate_samples(
        text=text,
        max_samples=count,
        batch_size=batch_size,
        noise_scales=[spec["noise"]],
        noise_scale_ws=[spec["noise"]],
        length_scales=[0.75, 1.0, 1.25],
        output_dir=set_dir(cfg, set_name),
        file_names=file_names,
        auto_reduce_batch_size=True,
    )


# --------------------------------------------------------------------------- #
# Stage-1 progress: count clips on disk across all four sets and extrapolate.
# A rich progress bar on a tty; the original plain per-poll line when output is
# captured (non-tty, e.g. under train_batch.py's log redirection).
# --------------------------------------------------------------------------- #
class StageOneProgress:
    def __init__(self, cfg: dict, total: int, interval: float | None = None):
        self._dirs = [set_dir(cfg, s) for s in SETS]
        self._total = total
        self._tty = sys.stdout.isatty()  # animate only on a real tty (not just forced color)
        self._interval = interval if interval is not None else (2.0 if self._tty else 5.0)
        self._stop = threading.Event()
        self._t = threading.Thread(target=self._loop, daemon=True)
        self._progress = None
        self._task = None

    def __enter__(self) -> "StageOneProgress":
        if self._tty:
            from rich.progress import (
                BarColumn,
                MofNCompleteColumn,
                Progress,
                TaskProgressColumn,
                TextColumn,
                TimeRemainingColumn,
            )

            self._progress = Progress(
                TextColumn("[bold]Stage 1 synth[/]"),
                BarColumn(),
                MofNCompleteColumn(),
                TaskProgressColumn(),
                TimeRemainingColumn(compact=True),
                console=console,
            )
            self._progress.start()
            self._task = self._progress.add_task("synth", total=self._total)
        self._t.start()
        return self

    def __exit__(self, *exc) -> None:
        self._stop.set()
        self._t.join(timeout=2.0)
        if self._progress is not None:
            self._progress.update(self._task, completed=min(self._count(), self._total))
            self._progress.stop()

    def _count(self) -> int:
        return sum(count_wavs(d) for d in self._dirs)

    def _loop(self) -> None:
        start = time.monotonic()
        start_count = self._count()  # clips already on disk (prior run) — exclude from the rate
        last_done = -1  # plain (non-tty) path prints a fresh line per poll; only when the count moves
        while not self._stop.wait(self._interval):
            done = self._count()
            if self._progress is not None:
                self._progress.update(self._task, completed=min(done, self._total))
                continue
            if done == last_done:  # nothing new on disk (e.g. workers still loading) — don't reprint
                continue
            last_done = done
            elapsed = time.monotonic() - start
            made = done - start_count  # clips produced this session (the basis for rate/ETA)
            pct = 100.0 * done / self._total if self._total else 0.0
            if made > 0 and elapsed > 8.0:
                rate = made / elapsed
                eta = (self._total - done) / rate if rate > 0 else 0
                console.print(
                    f"    Stage 1: {done}/{self._total} clips ({pct:.0f}%) · "
                    f"{rate:.1f} clips/s · ~{fmt_dur(eta)} left",
                    markup=False,
                )
            else:
                console.print(
                    f"    Stage 1: {done}/{self._total} clips ({pct:.0f}%) · warming up…",
                    markup=False,
                )


def fmt_dur(seconds: float) -> str:
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h{m:02d}m"
    if m:
        return f"{m}m{s:02d}s"
    return f"{s}s"


# --------------------------------------------------------------------------- #
# Orchestrator: fan out workers per set, poll ETA, verify counts.
# --------------------------------------------------------------------------- #
def run_set(cfg: dict, set_name: str, jobs: int, cores: int) -> None:
    spec = SETS[set_name]
    count = int(cfg[spec["count"]])
    out_dir = set_dir(cfg, set_name)
    os.makedirs(out_dir, exist_ok=True)

    existing = count_wavs(out_dir)
    if existing >= count:
        console.print(f"  [{set_name}] {existing} clips already present — skipping", markup=False)
        return
    remaining = count - existing

    workers = min(jobs, max(1, remaining // MIN_CHUNK))
    threads = max(1, cores // jobs)
    shares = [c for c in split_evenly(remaining, workers) if c > 0]
    console.print(
        f"  [{set_name}] {remaining} clips via {len(shares)} worker(s) "
        f"× {threads} thread(s){' (+' + str(existing) + ' existing)' if existing else ''}",
        markup=False,
    )

    procs = []
    for i, share in enumerate(shares):
        env = dict(os.environ, OMP_NUM_THREADS=str(threads))
        cmd = [
            sys.executable,
            __file__,
            "--worker",
            "--config",
            cfg["_config_path"],
            "--set",
            set_name,
            "--count",
            str(share),
            "--threads",
            str(threads),
        ]
        if spec["neg"] and i == 0:
            cmd.append("--with-custom")
        procs.append(subprocess.Popen(cmd, env=env))

    failed = [i for i, p in enumerate(procs) if p.wait() != 0]
    got = count_wavs(out_dir)
    if failed:
        console.print(f"  [{set_name}] WARNING: {len(failed)} worker(s) exited non-zero", markup=False)
    if got < count:
        # The monolith's resume guard self-heals a small shortfall (it tops up
        # single-threaded), but flag it loudly so a large miss is visible.
        console.print(f"  [{set_name}] WARNING: only {got}/{count} clips on disk", markup=False)


def run_orchestrator(cfg: dict, jobs: int, cores: int) -> None:
    phrases = cfg["target_phrase"]
    console.print(
        f"==> Stage 1 (parallel synth): {cfg['model_name']} · phrase={phrases[0]!r} · "
        f"jobs={jobs} cores={cores}",
        markup=False,
    )

    # Pre-warm the adversarial-text phonemizer once so its lazy model download
    # (if any) can't race across the negative-set workers.
    try:
        from openwakeword.data import generate_adversarial_texts

        generate_adversarial_texts(input_text=phrases[0], N=1, include_partial_phrase=1.0)
    except Exception as e:  # best-effort warm-up; workers still work without it
        console.print(f"    (adversarial-text pre-warm skipped: {e})", markup=False)

    total = 2 * int(cfg["n_samples"]) + 2 * int(cfg["n_samples_val"])
    t0 = time.monotonic()
    with StageOneProgress(cfg, total):
        for set_name in SETS:
            run_set(cfg, set_name, jobs, cores)

    elapsed = time.monotonic() - t0
    console.print(
        f"==> Stage 1 done in {fmt_dur(elapsed)}. Stages 2–3 (augment+features+train) "
        f"follow on {jobs} core(s) — usually a few minutes; the model is then exported.",
        markup=False,
    )


def load_cfg(path: str) -> dict:
    cfg = yaml.safe_load(Path(path).read_text())
    cfg["_config_path"] = path
    cfg["output_dir"] = os.path.abspath(cfg["output_dir"])
    return cfg


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", required=True, help="resolved training config YAML")
    ap.add_argument("--jobs", type=int, default=os.cpu_count() or 1, help="parallel synth workers")
    ap.add_argument("--cores", type=int, default=os.cpu_count() or 1, help="total core budget")
    ap.add_argument("--worker", action="store_true", help="internal: run one worker share")
    ap.add_argument("--set", choices=list(SETS), help="worker: which clip set")
    ap.add_argument("--count", type=int, help="worker: clips to generate")
    ap.add_argument("--threads", type=int, help="worker: torch threads")
    ap.add_argument("--with-custom", action="store_true", help="worker: include custom negatives")
    a = ap.parse_args()

    cfg = load_cfg(a.config)
    if a.worker:
        run_worker(cfg, a.set, a.count, a.threads, a.with_custom)
    else:
        run_orchestrator(cfg, max(1, a.jobs), max(1, a.cores))


if __name__ == "__main__":
    main()
