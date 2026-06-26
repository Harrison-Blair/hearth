"""Train a series of wake words with a live rich dashboard.

For each phrase: train (train.sh) -> gated eval (evaluate.py) -> commit. Weak models
are reported and skipped (not committed). One commit per passing model, committed in
a serial pass after the (optionally parallel) training wave so concurrent jobs never
touch models.json. This is a Python port of the original train_batch.sh, with the
per-phrase log streaming replaced by an in-place updating table.

Invoked via `bash training/train_batch.sh` (a thin shim that runs this under the
isolated training venv with cwd at the repo root). Gate (per model): true-positive
>= 90%, false-positive <= 1%, separation > 0.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

from manifest import slug as phrase_slug  # identical regex; single source of truth
from synth_clips import fmt_dur
from ui import console, rule, run_config_panel

PY = "training/.venv-train/bin/python"  # isolated training venv (see bootstrap.sh)
THRESHOLD = "0.6"  # match config.yaml wake.threshold
TITLE = "Wake-word training"
INSTALLED_RE = re.compile(r"installed at (.*\.onnx)")

LOCK = threading.Lock()  # guards table reads against the owning worker's writes


@dataclass
class PhraseState:
    idx: int
    phrase: str
    slug: str
    status: str = "queued"  # queued|training|evaluating|committing|
    #                         committed|passed|gate_failed|train_failed
    model: str | None = None  # scraped installed .onnx path
    model_slug: str | None = None  # basename(model) -> eval/positives/manifest paths
    evj: str | None = None
    tp: float | None = None
    fp: float | None = None
    sep: float | None = None
    train_secs: float | None = None
    eval_secs: float | None = None
    error: str | None = None

    @property
    def log(self) -> str:
        return f"training/work/{self.slug}.train.log"


# Globals set in main() (read by workers + renderer).
SMOKE = False
COMMIT = True
CPP = 1
TOTAL = 0
USE_LIVE = True
STREAM = False  # tee per-phrase train/eval output to the terminal (disables the table)


def _run_logged(cmd: list[str], log_path: str, mode: str) -> int:
    """Run cmd writing combined stdout/stderr to log_path. When STREAM is set,
    also echo each line to the terminal so a single run is visible live (the log
    is still written, so scrape_installed/read_metrics keep working)."""
    if not STREAM:
        with open(log_path, mode) as log:
            return subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT).returncode
    with open(log_path, mode) as log:
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             text=True, bufsize=1)
        for line in p.stdout:
            sys.stdout.write(line)
            log.write(line)
        return p.wait()


# --------------------------------------------------------------------------- #
# Phrase resolution (parity with train_batch.sh lines 39-53)
# --------------------------------------------------------------------------- #
def read_phrase_file(path: str) -> list[str]:
    phrases = []
    with open(path) as f:
        for line in f:
            line = line.split("#", 1)[0].strip()  # strip inline #-comments + whitespace
            if line:
                phrases.append(line)
    return phrases


def resolve_phrases(inputs: list[str]) -> list[str]:
    if not inputs:
        return read_phrase_file("training/phrases.txt")
    if len(inputs) == 1 and os.path.isfile(inputs[0]):
        return read_phrase_file(inputs[0])
    return inputs


# --------------------------------------------------------------------------- #
# State updates + plain-mode notifications
# --------------------------------------------------------------------------- #
def metrics_str(st: PhraseState) -> str:
    if st.tp is None:
        return ""
    return f"tp={st.tp * 100:.0f}% fp={st.fp * 100:.0f}% sep={st.sep:+.3f}"


def _notify(st: PhraseState) -> None:
    """Non-tty fallback: emit a transition line (mirrors the bash echoes)."""
    if USE_LIVE:
        return
    if st.status == "training":
        print(f"[{st.idx}/{TOTAL}] {st.phrase} — training (jobs={CPP})", flush=True)
    elif st.status in ("passed", "gate_failed", "train_failed", "committed"):
        label = {"passed": "PASS", "gate_failed": "gate FAILED",
                 "train_failed": "train FAILED", "committed": "committed"}[st.status]
        print(f"   [{st.phrase}] {label} {metrics_str(st)}".rstrip(), flush=True)


def set_status(st: PhraseState, status: str) -> None:
    with LOCK:
        st.status = status
    _notify(st)


def read_metrics(st: PhraseState) -> None:
    try:
        d = json.loads(open(st.evj).read())
    except (OSError, ValueError):
        return
    with LOCK:
        st.tp, st.fp, st.sep = d.get("tp_rate"), d.get("fp_rate"), d.get("separation")


def scrape_installed(log_path: str) -> str | None:
    try:
        text = open(log_path).read()
    except OSError:
        return None
    m = INSTALLED_RE.search(text)  # train.sh prints exactly one "installed at <path>"
    return m.group(1).strip() if m else None


# --------------------------------------------------------------------------- #
# Worker: one phrase, train -> gated eval (parity with train_and_eval())
# --------------------------------------------------------------------------- #
def _train_one(st: PhraseState) -> None:
    os.makedirs("training/work", exist_ok=True)
    smoke = ["--smoke"] if SMOKE else []

    set_status(st, "training")
    t0 = time.monotonic()
    rc = _run_logged(
        ["bash", "training/train.sh", "--phrase", st.phrase, "--jobs", str(CPP), *smoke],
        st.log, "w",
    )
    st.train_secs = time.monotonic() - t0

    model = scrape_installed(st.log)
    if not model or not os.path.isfile(model):
        st.error = f"train.sh failed (rc={rc}); see {st.log}"
        set_status(st, "train_failed")
        return
    st.model = model
    st.model_slug = os.path.basename(model)[: -len(".onnx")]
    st.evj = f"training/work/{st.model_slug}.eval.json"

    set_status(st, "evaluating")
    t0 = time.monotonic()
    rc = _run_logged(
        [PY, "training/evaluate.py", "--model", model,
         "--positives", f"training/work/{st.model_slug}/positive_test",
         "--backgrounds", "training/data/audioset_16k",
         "--threshold", THRESHOLD, "--gate", "--json", st.evj],
        st.log, "a",
    )
    st.eval_secs = time.monotonic() - t0
    read_metrics(st)  # evaluate.py writes the JSON before the gate exit, so metrics exist
    set_status(st, "passed" if rc == 0 else "gate_failed")


def train_one(st: PhraseState) -> None:
    try:
        _train_one(st)
    except Exception as e:  # a worker must never abort the wave
        with LOCK:
            st.status, st.error = "train_failed", str(e)


# --------------------------------------------------------------------------- #
# Dashboard
# --------------------------------------------------------------------------- #
ACTIVE = {"training", "evaluating", "committing"}
TERMINAL = {
    "queued": "[dim]queued[/]",
    "committed": "[green]✓ committed[/]",
    "passed": "[green]✓ passed[/]",
    "gate_failed": "[red]✗ gate failed[/]",
    "train_failed": "[red]✗ train failed[/]",
}


def build_table(states: list[PhraseState]):
    from rich.spinner import Spinner
    from rich.table import Table

    t = Table(title=TITLE, expand=False)
    t.add_column("#", justify="right")
    t.add_column("phrase")
    t.add_column("status")
    t.add_column("tp", justify="right")
    t.add_column("fp", justify="right")
    t.add_column("sep", justify="right")
    t.add_column("elapsed", justify="right")
    with LOCK:
        for s in states:
            status = Spinner("dots", text=s.status) if s.status in ACTIVE else TERMINAL[s.status]
            tp = f"{s.tp * 100:.0f}%" if s.tp is not None else ""
            fp = f"{s.fp * 100:.0f}%" if s.fp is not None else ""
            sep = f"{s.sep:+.3f}" if s.sep is not None else ""
            secs = (s.train_secs or 0) + (s.eval_secs or 0)
            elapsed = fmt_dur(secs) if secs else ""
            t.add_row(str(s.idx), s.phrase, status, tp, fp, sep, elapsed)
    return t


# --------------------------------------------------------------------------- #
# Commit pass: serial, input order (parity with train_batch.sh lines 124-154)
# --------------------------------------------------------------------------- #
def commit_one(st: PhraseState) -> None:
    subprocess.run([PY, "training/manifest.py", "upsert", st.model_slug,
                    "--phrase", st.phrase, "--eval", st.evj], capture_output=True)
    # -f: models/wake/* is git-ignored, but trained models are distributed in-repo.
    subprocess.run(["git", "add", "-f", st.model, "models/wake/models.json"], capture_output=True)
    msg = (
        f'Add wake-word model: "{st.phrase}"\n\n'
        f'Trained openWakeWord model for "{st.phrase}" -> {st.model}.\n'
        "Gated eval (tp/fp/separation) passed; recorded in models/wake/models.json.\n\n"
        "Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
    )
    subprocess.run(["git", "commit", "-q", "-m", msg], capture_output=True)


def commit_pass(states: list[PhraseState], refresh) -> None:
    if not COMMIT:
        return
    for st in states:
        if st.status != "passed":
            continue
        set_status(st, "committing")
        refresh()
        commit_one(st)
        set_status(st, "committed")
        refresh()


# --------------------------------------------------------------------------- #
# Summary (parity with train_batch.sh lines 156-157)
# --------------------------------------------------------------------------- #
def summary_line(st: PhraseState) -> str:
    m = metrics_str(st)
    if st.status == "committed":
        return f"[green]OK committed[/]  {m}  {st.phrase}"
    if st.status == "passed":
        return f"[green]OK no-commit[/]  {m}  {st.phrase}"
    if st.status == "gate_failed":
        return f"[red]FAIL(gate)[/]    {m or 'no metrics'}  {st.phrase}"
    return f"[red]FAIL(train)[/]  {st.phrase}"


# --------------------------------------------------------------------------- #
# Waves
# --------------------------------------------------------------------------- #
def run_wave(states: list[PhraseState], jobs: int) -> None:
    if USE_LIVE:
        from rich.live import Live

        with Live(build_table(states), console=console, auto_refresh=False) as live:
            def refresh():
                live.update(build_table(states))
                live.refresh()

            with ThreadPoolExecutor(max_workers=jobs) as ex:
                futures = [ex.submit(train_one, s) for s in states]
                while not all(f.done() for f in futures):
                    refresh()
                    time.sleep(0.1)
            refresh()
            commit_pass(states, refresh)
            refresh()
    else:
        with ThreadPoolExecutor(max_workers=jobs) as ex:
            futures = [ex.submit(train_one, s) for s in states]
            for f in as_completed(futures):
                f.result()  # train_one never raises
        commit_pass(states, lambda: None)


# --------------------------------------------------------------------------- #
def main() -> int:
    global SMOKE, COMMIT, CPP, TOTAL, USE_LIVE, STREAM

    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            "  bash training/train_batch.sh                       # phrases from training/phrases.txt\n"
            "  bash training/train_batch.sh training/phrases.txt  # explicit phrases file\n"
            '  bash training/train_batch.sh "jarvis" "athena"     # phrases as args\n'
            "  bash training/train_batch.sh --smoke training/phrases.txt   # fast dry run\n"
            '  bash training/train_batch.sh --no-commit "jarvis"           # train+test only\n'
            "  bash training/train_batch.sh --jobs 4 training/phrases.txt  # 4 phrases at a time"
        ),
    )
    ap.add_argument("--smoke", action="store_true", help="fast end-to-end dry run")
    ap.add_argument("--no-commit", dest="commit", action="store_false", help="train+test only")
    ap.add_argument("--jobs", type=int, default=1, help="phrases to train concurrently")
    ap.add_argument("--stream", action="store_true",
                    help="stream per-phrase train/eval output to the terminal (disables the table)")
    ap.add_argument("inputs", nargs="*", help="phrases, or a phrases file")
    a = ap.parse_args()

    SMOKE, COMMIT, STREAM = a.smoke, a.commit, a.stream
    jobs = max(1, a.jobs)

    phrases = resolve_phrases(a.inputs)
    if not phrases:
        print("no phrases to train (edit training/phrases.txt)", file=sys.stderr)
        return 1

    TOTAL = len(phrases)
    # Split the core budget across concurrent phrases; with jobs=1 a single phrase
    # gets the whole budget (matching train.sh's nproc default) instead of 1 core.
    budget = int(os.environ.get("WW_CORES") or (os.cpu_count() or 1))
    CPP = max(1, budget // jobs)
    # Animate only on a real tty; --stream tees raw output instead of the table.
    USE_LIVE = sys.stdout.isatty() and not STREAM

    states = [PhraseState(idx=i, phrase=p, slug=phrase_slug(p)) for i, p in enumerate(phrases, 1)]

    console.print(run_config_panel([
        f"[bold]phrases[/] {TOTAL}{'  (smoke)' if SMOKE else ''}",
        f"[bold]jobs[/]    {jobs} × {CPP} core(s)",
        f"[bold]commit[/]  {'yes' if COMMIT else 'no (--no-commit)'}",
    ], title="Batch training"))

    try:
        run_wave(states, jobs)
    except KeyboardInterrupt:
        console.print("[red]aborted[/]")
        return 1

    rule("summary")
    for st in states:
        console.print(f"  {summary_line(st)}")
    return 1 if any(s.status in ("train_failed", "gate_failed") for s in states) else 0


if __name__ == "__main__":
    sys.exit(main())
