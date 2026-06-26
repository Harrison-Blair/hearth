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
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"
PY="training/.venv-train/bin/python"   # isolated training venv (see bootstrap.sh)

PHRASE=""; NAME=""; SMOKE=0; CFG=""
while [ $# -gt 0 ]; do
  case "$1" in
    --phrase) PHRASE="${2:?--phrase needs a value}"; shift 2;;
    --name)   NAME="${2:?--name needs a value}"; shift 2;;
    --smoke)  SMOKE=1; shift;;
    -h|--help) sed -n '2,11p' "$0"; exit 0;;
    *.yml|*.yaml) CFG="$1"; shift;;
    *) echo "unknown argument: $1" >&2; exit 1;;
  esac
done

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
# openWakeWord 0.6.0 unconditionally attempts an ONNX->tflite conversion after the
# ONNX export; that needs TensorFlow/onnx_tf, which we intentionally don't install.
# The ONNX (all the runtime needs) is written first, so tolerate the tflite failure
# and verify the ONNX actually landed.
"$PY" -m openwakeword.train --training_config "$CFG" --generate_clips --augment_clips --train_model || true
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
