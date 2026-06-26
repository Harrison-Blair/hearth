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
#   bash training/train_batch.sh --jobs 4 training/phrases.txt  # 4 phrases at a time
#
# --jobs P trains P phrases concurrently, splitting the $WW_CORES (default nproc)
# core budget so each phrase gets P-th of the cores. Commits are serialized after
# the parallel wave (one commit per model, in input order). Default P=1 is the
# original sequential run with live per-phrase log streaming.
#
# Gate (per model): true-positive >= 90%, false-positive <= 1%, separation > 0.
set -uo pipefail

cd "$(git rev-parse --show-toplevel)"
PY="training/.venv-train/bin/python"   # isolated training venv (see bootstrap.sh)
THRESHOLD=0.6                          # match config.yaml wake.threshold

SMOKE=""; COMMIT=1; JOBS=1; INPUTS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --smoke) SMOKE="--smoke"; shift;;
    --no-commit) COMMIT=0; shift;;
    --jobs) JOBS="${2:?--jobs needs a value}"; shift 2;;
    -h|--help) sed -n '2,20p' "$0"; exit 0;;
    *) INPUTS+=("$1"); shift;;
  esac
done

# Phrases come from a file (no args -> phrases.txt, or a single arg that is a
# file) or are the args themselves.
PHRASES=()
read_file() {  # strip #-comments and surrounding whitespace; keep non-empty lines
  while IFS= read -r line || [ -n "$line" ]; do  # || ...: keep a final line with no trailing newline
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

TOTAL=${#PHRASES[@]}
# Per-phrase core budget: split $WW_CORES across the P concurrent phrases.
CPP=1
if [ "$JOBS" -gt 1 ]; then
  B="${WW_CORES:-$(nproc)}"
  CPP=$(( B / JOBS )); [ "$CPP" -lt 1 ] && CPP=1
fi
echo "==> Training ${TOTAL} phrase(s)${SMOKE:+ (smoke)} — jobs=${JOBS}${JOBS:+ × ${CPP} core(s)}"

# slug used for a phrase's log + result file (phrase-based; matches make_config slug
# minus any _smoke suffix). The model slug read back from .batchresult may add _smoke.
phrase_slug() { printf '%s' "$1" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9]\+/_/g;s/^_//;s/_$//'; }

# metrics <evj> -> "tp=NN% fp=NN% sep=+0.NNN" from the eval json evaluate.py wrote.
metrics() { "$PY" -c "import json;d=json.load(open('$1'));print('tp=%.0f%% fp=%.0f%% sep=%+.3f'%(d['tp_rate']*100,d['fp_rate']*100,d['separation']))"; }

# Train one phrase (train.sh --jobs CPP) + gated eval. Writes a one-line result file
# work/<slug>.batchresult = "STATUS<TAB>slug<TAB>model<TAB>evj<TAB>phrase". No git
# here: commits run in a serial pass so parallel jobs never touch models.json/index.
train_and_eval() {  # <idx> <phrase> <stream:0|1>
  local idx="$1" phrase="$2" stream="$3"
  local s log res model slug evj t0
  s="$(phrase_slug "$phrase")"; s="${s:-wakeword}"
  log="training/work/${s}.train.log"; res="training/work/${s}.batchresult"
  rm -f "$res"
  echo "============ [$idx/$TOTAL] $phrase  (jobs=$CPP) ==> $log"
  t0=$SECONDS
  # train.sh prints "installed at <path>.onnx". Stream live for a single sequential
  # run; redirect to the log in parallel mode (interleaved live output is unreadable).
  if [ "$stream" -eq 1 ]; then
    bash training/train.sh --phrase "$phrase" --jobs "$CPP" $SMOKE 2>&1 | tee "$log" || true
  else
    bash training/train.sh --phrase "$phrase" --jobs "$CPP" $SMOKE >"$log" 2>&1 || true
  fi
  echo "   [$phrase] train step: $((SECONDS - t0))s"
  model="$(sed -n 's/.*installed at \(.*\.onnx\).*/\1/p' "$log" | head -1)"
  if [ -z "$model" ] || [ ! -f "$model" ]; then
    printf 'FAIL_TRAIN\t\t\t\t%s\n' "$phrase" > "$res"
    echo "!! [$phrase] train failed (see $log)"; return
  fi
  slug="$(basename "$model" .onnx)"; evj="training/work/${slug}.eval.json"
  t0=$SECONDS
  # Gate: true-positive / false-positive / separation against held-out clips.
  if "$PY" training/evaluate.py --model "$model" \
       --positives "training/work/${slug}/positive_test" \
       --backgrounds training/data/audioset_16k \
       --threshold "$THRESHOLD" --gate --json "$evj"; then
    printf 'OK\t%s\t%s\t%s\t%s\n' "$slug" "$model" "$evj" "$phrase" > "$res"
    echo "   [$phrase] eval step: $((SECONDS - t0))s — PASS"
  else
    # evaluate.py writes the json before the gate exit, so metrics stay available.
    printf 'FAIL_GATE\t%s\t%s\t%s\t%s\n' "$slug" "$model" "$evj" "$phrase" > "$res"
    echo "   [$phrase] eval step: $((SECONDS - t0))s — gate FAILED"
  fi
}

# ---- Train+eval wave: sequential (live) for jobs=1, else a bounded parallel pool.
IDX=0
if [ "$JOBS" -le 1 ]; then
  for phrase in "${PHRASES[@]}"; do IDX=$((IDX + 1)); echo; train_and_eval "$IDX" "$phrase" 1; done
else
  for phrase in "${PHRASES[@]}"; do
    IDX=$((IDX + 1))
    while [ "$(jobs -r -p | wc -l)" -ge "$JOBS" ]; do wait -n; done  # hold at P in flight
    train_and_eval "$IDX" "$phrase" 0 &
  done
  wait
fi

# ---- Serial commit pass: in input order, read each result and commit OK models.
echo; echo "==================== results ===================="
SUMMARY=(); FAILED=0
for phrase in "${PHRASES[@]}"; do
  s="$(phrase_slug "$phrase")"; s="${s:-wakeword}"; res="training/work/${s}.batchresult"
  if [ ! -f "$res" ]; then SUMMARY+=("FAIL(train)  $phrase"); FAILED=1; continue; fi
  IFS=$'\t' read -r status slug model evj _ < "$res"
  case "$status" in
    OK)
      m="$(metrics "$evj")"
      if [ "$COMMIT" -eq 1 ]; then
        "$PY" training/manifest.py upsert "$slug" --phrase "$phrase" --eval "$evj"
        # -f: models/wake/* is git-ignored, but trained models are distributed in-repo.
        git add -f "$model" models/wake/models.json
        git commit -q -m "Add wake-word model: \"$phrase\"

Trained openWakeWord model for \"$phrase\" -> $model.
Gated eval (tp/fp/separation) passed; recorded in models/wake/models.json.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
        echo "++ committed $slug ($m)"; SUMMARY+=("OK committed  $m  $phrase")
      else
        echo "++ passed $slug ($m) [--no-commit]"; SUMMARY+=("OK no-commit  $m  $phrase")
      fi;;
    FAIL_GATE)
      m="$([ -f "$evj" ] && metrics "$evj" || echo "no metrics")"
      echo "!! gate failed for '$phrase' ($m) — skipping commit"
      SUMMARY+=("FAIL(gate)    $m  $phrase"); FAILED=1;;
    *) SUMMARY+=("FAIL(train)  $phrase"); FAILED=1;;
  esac
done

echo; echo "==================== summary ===================="
printf '  %s\n' "${SUMMARY[@]}"
exit $FAILED
