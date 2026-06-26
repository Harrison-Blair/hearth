#!/usr/bin/env bash
# Train an openWakeWord model and install the resulting .onnx into models/wake/.
# Prerequisite: bash training/bootstrap.sh  (deps + data).
#
# Usage (from repo root):
#   bash training/train.sh                            # default phrase (wakeword.yml), full run
#   bash training/train.sh --smoke                    # default phrase, fast validation run
#   bash training/train.sh --phrase "hey jarvis"      # new phrase, full run
#   bash training/train.sh --phrase "athena" --smoke  # new phrase, fast validation
#   bash training/train.sh --phrase "friday" --name fri   # override the model name
#   bash training/train.sh training/my.yml            # run an explicit config file
#   bash training/train.sh --phrase "athena" --jobs 16    # use 16 cores (default: nproc)
#
# --jobs N runs this whole training with a budget of N cores: Stage 1 (the slow
# Piper clip synthesis) is sharded across N worker processes, and Stages 2-3
# (features/train) use N threads. Default N = $WW_JOBS or nproc. --jobs 1 is the
# original single-process behavior. Lower --jobs if you hit memory pressure.
#
# Multi-word phrases: ALWAYS quote the whole phrase so it stays one argument.
#   bash training/train.sh --phrase "ok computer"     # trains ONE model
#   bash training/train.sh --phrase "hey assistant"   # fires on the full phrase
# A quoted multi-word phrase trains a single model that wakes only on the whole
# phrase ("hey assistant"), not on "hey" or "assistant" alone. Without quotes the
# words become separate arguments and only the first is used as the phrase.
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"
PY="training/.venv-train/bin/python"   # isolated training venv (see bootstrap.sh)

PHRASE=""; NAME=""; SMOKE=0; CFG=""; JOBS=""
while [ $# -gt 0 ]; do
  case "$1" in
    --phrase) PHRASE="${2:?--phrase needs a value}"; shift 2;;
    --name)   NAME="${2:?--name needs a value}"; shift 2;;
    --jobs)   JOBS="${2:?--jobs needs a value}"; shift 2;;
    --smoke)  SMOKE=1; shift;;
    -h|--help) sed -n '2,24p' "$0"; exit 0;;
    *.yml|*.yaml) CFG="$1"; shift;;
    *) echo "unknown argument: $1" >&2; exit 1;;
  esac
done
JOBS="${JOBS:-${WW_JOBS:-$(nproc)}}"   # core budget for this run (synth shards + stage 2-3 threads)

# --phrase / --smoke stamp a config from wakeword.yml; an explicit *.yml is used
# as-is; bare `train.sh` trains the default phrase straight from wakeword.yml.
if [ -n "$PHRASE" ] || [ "$SMOKE" -eq 1 ]; then
  gen_args=()
  [ -n "$PHRASE" ] && gen_args+=(--phrase "$PHRASE")
  [ -n "$NAME" ] && gen_args+=(--name "$NAME")
  [ "$SMOKE" -eq 1 ] && gen_args+=(--smoke)
  CFG=$("$PY" training/make_config.py "${gen_args[@]}")
  echo "==> Generated config: $CFG"
fi
CFG="${CFG:-training/wakeword.yml}"
MODEL=$("$PY" -c "import yaml; print(yaml.safe_load(open('$CFG'))['model_name'])")

# Stage 1: Piper synthesizes positive + adversarial-negative clips (slowest step).
# Stage 2: augment clips and compute openWakeWord features.
# Stage 3: train the DNN classifier and export ONNX (no tflite — runtime uses ONNX).
SRC="training/work/${MODEL}.onnx"
rm -f "$SRC"

# Up-front summary so the scale of the (long, quiet) run is visible before Piper
# starts synthesizing. Read straight from the resolved config.
"$PY" - "$CFG" <<'PY'
import sys, yaml
c = yaml.safe_load(open(sys.argv[1]))
smoke = "yes" if c["model_name"].endswith("_smoke") else "no"
print("==> Run config:")
print(f"    model={c['model_name']}  phrase={c['target_phrase'][0]!r}  smoke={smoke}")
print(f"    n_samples={c['n_samples']}  n_samples_val={c['n_samples_val']}  steps={c['steps']}")
print("    Stage 1 (Piper clip synthesis) is the slowest and quietest — be patient.")
PY

# Stage 1 parallelism: with --jobs > 1, pre-synthesize the clip sets across JOBS
# worker processes (with a JOBS-clip-per-second ETA). openwakeword.train then finds
# the dirs full and skips its own sequential generation. --jobs 1 leaves Stage 1 to
# the monolith exactly as before. --cores=JOBS keeps each worker single-threaded so
# the run stays within its JOBS-core budget (and batches don't oversubscribe).
if [ "$JOBS" -gt 1 ]; then
  "$PY" training/synth_clips.py --config "$CFG" --jobs "$JOBS" --cores "$JOBS"
fi
# Stages 2-3 (feature extraction + dataloader) read OWW_NCPU for their thread count
# (see the bootstrap.sh patch); same JOBS budget flows through all three stages.
export OWW_NCPU="$JOBS"

# openWakeWord 0.6.0 unconditionally attempts an ONNX->tflite conversion after the
# ONNX export; that needs TensorFlow/onnx_tf, which we intentionally don't install.
# The ONNX (all the runtime needs) is written first, so tolerate the tflite failure
# and verify the ONNX actually landed.
t0=$SECONDS
# Stream output live, but collapse just the trailing onnx_tf traceback (the
# expected tflite-conversion failure) into one line. Any other traceback is
# flushed verbatim at EOF, so a real failure still shows its full stack.
"$PY" -m openwakeword.train --training_config "$CFG" --generate_clips --augment_clips --train_model 2>&1 \
  | awk '
      /^Traceback \(most recent call last\):/ { buffering=1; buf=$0; next }
      buffering { buf=buf ORS $0; if ($0 ~ /onnx_tf/) tflite=1; next }
      { print; next }
      END {
        if (buffering && tflite)
          print "==> Skipping ONNX->tflite conversion (expected; runtime uses ONNX)."
        else if (buffering)
          print buf
      }
    ' || true
echo "==> generate+augment+train took $((SECONDS - t0))s"
[ -f "$SRC" ] || { echo "ERROR: training did not produce $SRC" >&2; exit 1; }

DST="models/wake/${MODEL}.onnx"
mkdir -p "$(dirname "$DST")"
cp "$SRC" "$DST"
PHRASE_OUT=$("$PY" -c "import yaml; print(yaml.safe_load(open('$CFG'))['target_phrase'][0])")
echo "==> Trained model installed at $DST"
echo "    Wire it up in config.yaml:"
echo "      wake:"
echo "        phrase: \"$PHRASE_OUT\""
echo "        model_path: \"$DST\""
