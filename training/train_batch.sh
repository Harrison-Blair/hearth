#!/usr/bin/env bash
# Train a series of wake words: for each phrase, train -> gated eval -> commit.
# Weak models are reported and skipped (not committed). One commit per model.
# Prerequisite: bash training/bootstrap.sh  (deps + data).
#
# Usage (from repo root):
#   bash training/train_batch.sh                       # phrases from training/phrases.txt
#   bash training/train_batch.sh training/phrases.txt  # explicit phrases file
#   bash training/train_batch.sh "jarvis" "athena"     # phrases as args
#   bash training/train_batch.sh --smoke training/phrases.txt   # fast end-to-end dry run
#   bash training/train_batch.sh --no-commit "jarvis"           # train+test only
#
# Gate (per model): true-positive >= 90%, false-positive <= 1%, separation > 0.
set -uo pipefail

cd "$(git rev-parse --show-toplevel)"
PY="training/.venv-train/bin/python"   # isolated training venv (see bootstrap.sh)
THRESHOLD=0.6                          # match config.yaml wake.threshold

SMOKE=""; COMMIT=1; INPUTS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --smoke) SMOKE="--smoke"; shift;;
    --no-commit) COMMIT=0; shift;;
    -h|--help) sed -n '2,16p' "$0"; exit 0;;
    *) INPUTS+=("$1"); shift;;
  esac
done

# Phrases come from a file (no args -> phrases.txt, or a single arg that is a
# file) or are the args themselves.
PHRASES=()
read_file() {  # strip #-comments and surrounding whitespace; keep non-empty lines
  while IFS= read -r line; do
    line="$(printf '%s' "${line%%#*}" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
    [ -n "$line" ] && PHRASES+=("$line")
  done < "$1"
}
if [ "${#INPUTS[@]}" -eq 0 ]; then
  read_file training/phrases.txt
elif [ "${#INPUTS[@]}" -eq 1 ] && [ -f "${INPUTS[0]}" ]; then
  read_file "${INPUTS[0]}"
else
  PHRASES=("${INPUTS[@]}")
fi
[ "${#PHRASES[@]}" -eq 0 ] && { echo "no phrases to train (edit training/phrases.txt)" >&2; exit 1; }

echo "==> Training ${#PHRASES[@]} phrase(s)${SMOKE:+ (smoke)}${COMMIT:+}"
SUMMARY=(); FAILED=0

for phrase in "${PHRASES[@]}"; do
  echo; echo "================ $phrase ================"
  # train.sh installs models/wake/<slug>.onnx and prints "installed at <path>".
  out="$(bash training/train.sh --phrase "$phrase" $SMOKE 2>&1)" || { echo "$out"; }
  echo "$out" | tail -5
  model="$(echo "$out" | sed -n 's/.*installed at \(.*\.onnx\).*/\1/p' | head -1)"
  if [ -z "$model" ] || [ ! -f "$model" ]; then
    echo "!! train failed for '$phrase'"; SUMMARY+=("FAIL(train)  $phrase"); FAILED=1; continue
  fi
  slug="$(basename "$model" .onnx)"
  evj="training/work/${slug}.eval.json"

  # Gate: true-positive / false-positive / separation against held-out clips.
  if "$PY" training/evaluate.py --model "$model" \
       --positives "training/work/${slug}/positive_test" \
       --backgrounds training/data/audioset_16k \
       --threshold "$THRESHOLD" --gate --json "$evj"; then
    tp="$("$PY" -c "import json;print('%.0f%%'%(json.load(open('$evj'))['tp_rate']*100))")"
    if [ "$COMMIT" -eq 1 ]; then
      "$PY" training/manifest.py upsert "$slug" --phrase "$phrase" --eval "$evj"
      # -f: models/wake/* is git-ignored, but trained models are distributed in-repo.
      git add -f "$model" models/wake/models.json
      git commit -q -m "Add wake-word model: \"$phrase\"

Trained openWakeWord model for \"$phrase\" -> $model.
Gated eval (tp/fp/separation) passed; recorded in models/wake/models.json.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
      echo "++ committed $slug ($tp)"; SUMMARY+=("OK committed $tp  $phrase")
    else
      echo "++ passed $slug ($tp) [--no-commit]"; SUMMARY+=("OK no-commit $tp  $phrase")
    fi
  else
    echo "!! gate failed for '$phrase' — skipping commit"; SUMMARY+=("FAIL(gate)   $phrase"); FAILED=1
  fi
done

echo; echo "==================== summary ===================="
printf '  %s\n' "${SUMMARY[@]}"
exit $FAILED
