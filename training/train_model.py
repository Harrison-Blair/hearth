"""Run the openWakeWord generate/augment/train step behind a clean rich UI.

`python -m openwakeword.train --generate_clips --augment_clips --train_model` is
Stages 2-3 of a run, but raw it dumps root-logger `####` banners, four restarting
`tqdm` bars, and `torch_audiomentations` FutureWarning spam. This wrapper runs it
as a subprocess and translates that firehose into per-phase progress bars — the
same treatment Stage 1 gets in synth_clips.py: a tty-gated `rich.progress` with
ETA, degrading to plain `Phase: cur/total (NN%)` lines when stdout is captured
(non-tty, e.g. under train_batch.py's log redirection).

Load-bearing behaviors preserved from the old train.sh awk filter: the expected
ONNX->tflite traceback (onnx_tf, no TensorFlow installed) is collapsed to one
line, any *other* traceback is flushed verbatim, and the exit code is the
subprocess's so train.sh's `|| true` + ONNX-exists check stays the success oracle.

  python train_model.py --config CFG
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys

from ui import console  # shared rich console (degrades to plain when not a tty)

ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]")
LOG_PREFIX_RE = re.compile(r"^(?P<level>DEBUG|INFO|WARNING|ERROR|CRITICAL):root:")
# tqdm repaint: "desc:  99%|███| 124/125 [00:11<00:00, 10.66it/s]"
TQDM_RE = re.compile(r"^(?P<desc>.+?):\s*\d+%\|.*?\|\s*(?P<cur>\d+)/(?P<total>\d+)")
# count-only tqdm with no total: "Trimming empty rows: 2it [00:00, 288.86it/s]"
TQDM_COUNT_RE = re.compile(r"^.+?:\s*\d+it \[\d")
HASHES_RE = re.compile(r"^#+$")


def detect_phase(line: str) -> str | None:
    """Map an openWakeWord banner line to a phase heading (None if not a banner)."""
    if "Starting training sequence" in line:
        m = re.search(r"sequence (\d+)", line)
        return f"Training (seq {m.group(1)})" if m else "Training"
    if "Generating positive clips" in line or "Generating negative clips" in line:
        return "Generate clips"
    if "Skipping generation" in line:
        return "Generate clips (cached)"
    if "Computing openwakeword features" in line:
        return "Compute features"
    if "Openwakeword features already exist" in line:
        return "Compute features (cached)"
    if "Merging checkpoints" in line:
        return "Merge checkpoints"
    if "Saving ONNX mode" in line:
        return "Export ONNX"
    return None


def bar_label(desc: str, phase: str | None) -> str | None:
    """Map a tqdm desc to the bar it drives (None swallows the bar)."""
    d = desc.strip()
    if d == "Computing features":
        return "Compute features"
    if d == "Training":
        # The "Starting training sequence N" banner set the phase; key the bar to
        # it so the three sequences get three distinct bars.
        return phase if phase and phase.startswith("Training") else "Training"
    return None  # Trimming empty rows / Find best checkpoints / Predicting — minor


class Renderer:
    """Push-driven progress: phase headings + per-phase bars, tty or plain."""

    def __init__(self) -> None:
        self._tty = sys.stdout.isatty()  # animate only on a real tty
        self._progress = None
        self._tasks: dict[str, int] = {}
        self._phase: str | None = None
        self._deciles: dict[str, int] = {}  # plain path: last printed 10% step per bar

    def __enter__(self) -> "Renderer":
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
                TextColumn("[bold]{task.description}[/]"),
                BarColumn(),
                MofNCompleteColumn(),
                TaskProgressColumn(),
                TimeRemainingColumn(compact=True),
                console=console,
            )
            self._progress.start()
        return self

    def __exit__(self, *exc) -> None:
        if self._progress is not None:
            self._progress.stop()

    def phase(self, label: str) -> None:
        if label == self._phase:
            return
        self._phase = label
        if self._progress is not None:
            self._progress.console.print(f"[dim]==>[/] {label}")
        else:
            console.print(f"==> {label}", markup=False)

    def bar(self, label: str, cur: int, total: int) -> None:
        if self._progress is not None:
            tid = self._tasks.get(label)
            if tid is None:
                tid = self._progress.add_task(label, total=total)
                self._tasks[label] = tid
            self._progress.update(tid, total=total, completed=cur)
            return
        # Plain path: one line per 10% so captured logs stay readable.
        decile = (10 * cur // total) if total else 0
        if decile != self._deciles.get(label):
            self._deciles[label] = decile
            pct = 100.0 * cur / total if total else 0.0
            console.print(f"    {label}: {cur}/{total} ({pct:.0f}%)", markup=False)

    def note(self, text: str) -> None:
        # markup=False everywhere: text may be arbitrary subprocess output.
        if self._progress is not None:
            self._progress.console.print(text, markup=False)
        else:
            console.print(text, markup=False)


def strip_prefix(line: str) -> str:
    return LOG_PREFIX_RE.sub("", line)


def run(config: str) -> int:
    cmd = [
        sys.executable,
        "-m",
        "openwakeword.train",
        "--training_config",
        config,
        "--generate_clips",
        "--augment_clips",
        "--train_model",
    ]
    # PYTHONWARNINGS=ignore silences the torch_audiomentations FutureWarning flood
    # at its source (the subprocess analog of synth_clips.run_worker's
    # warnings.filterwarnings). OWW_NCPU (exported by train.sh) is inherited.
    env = dict(os.environ, PYTHONWARNINGS="ignore")
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1, env=env
    )

    # Once a traceback starts it runs to EOF (the expected tflite failure is last);
    # buffer it and decide at the end — collapse if onnx_tf, else flush verbatim.
    tb: list[str] | None = None
    tb_tflite = False

    with Renderer() as ui:
        assert proc.stdout is not None
        for raw in proc.stdout:
            line = raw.rstrip("\n")
            clean = strip_prefix(ANSI_RE.sub("", line)).strip()

            if tb is not None:
                tb.append(line)
                if "onnx_tf" in line:
                    tb_tflite = True
                continue
            if clean.startswith("Traceback (most recent call last):"):
                tb = [line]
                tb_tflite = False
                continue

            if not clean or HASHES_RE.match(clean):
                continue  # blank lines and #### separators

            m = TQDM_RE.match(clean)
            if m:
                label = bar_label(m.group("desc"), ui._phase)
                if label is not None:
                    ui.bar(label, int(m.group("cur")), int(m.group("total")))
                continue  # swallow all tqdm noise (rendered or not)
            if TQDM_COUNT_RE.match(clean):
                continue  # indeterminate tqdm (Trimming empty rows, etc.)

            phase = detect_phase(clean)
            if phase is not None:
                ui.phase(phase)
                continue

            if clean.startswith("Final Model "):
                ui.note(f"✓ {clean}")
                continue

            level = LOG_PREFIX_RE.match(line)
            if level:
                # Drop INFO/DEBUG chatter; surface real warnings/errors cleanly.
                if level.group("level") in ("WARNING", "ERROR", "CRITICAL"):
                    ui.note(clean)
                continue

            ui.note(clean)  # unrecognized, unprefixed — pass through verbatim

        if tb is not None:
            if tb_tflite:
                console.print(
                    "==> Skipping ONNX->tflite conversion (expected; runtime uses ONNX).",
                    markup=False,
                )
            else:
                for ln in tb:
                    console.print(ln, markup=False)

    return proc.wait()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", required=True, help="resolved training config YAML")
    a = ap.parse_args()
    sys.exit(run(a.config))


if __name__ == "__main__":
    main()
