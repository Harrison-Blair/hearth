# Custom wake word

Trains the openWakeWord model the runtime wakes on, replacing the stock
`hey_jarvis` bootstrap (`assistant/wake/openwakeword_detector.py`,
`config.yaml` → `wake`). This is **Phase 2a** of the MVP plan. Default phrase:
`hey assistant` (change it — see below).

The runtime loads ONNX, so we train and export `.onnx` only — the entire
TensorFlow / tflite-conversion stack from the upstream notebook is skipped.

## How it works

Fully synthetic, no recordings:

1. **Piper TTS** (dscripka's espeak-based sample-generator fork — works on
   Python 3.12) synthesizes ~20k positive clips plus phoneme-overlap adversarial
   negatives, across many speakers/pitches/speeds.
2. Clips are **augmented** with room reverb (MIT impulse responses) and mixed
   with **background audio** (an AudioSet noise/music slice), then turned into
   openWakeWord embedding features.
3. A small **DNN classifier** trains against those positives and ~2000 hours of
   pre-computed negative features, with a false-positive validation set for
   early stopping. Output: `<model_name>.onnx`.

Training runs in an **isolated venv** (`training/.venv-train`) with an older,
coherent scientific stack — the 2023-era openWakeWord training deps conflict with
the assistant runtime's versions. The runtime only consumes the trained `.onnx`,
so the two never share an environment. `bootstrap.sh` builds this venv; the
scripts call it directly, so you don't activate anything.

## Run it

From the repo root:

```bash
bash training/bootstrap.sh        # one-time: isolated venv + ~18 GB data (resumable)
bash training/train.sh --smoke    # ~2k-sample validation run (<1 hr) — prove it works
bash training/train.sh            # full run -> models/wake/hey_assistant.onnx
```

`train.sh` installs the model to `models/wake/<model_name>.onnx` and prints the
exact `config.yaml` lines to set, e.g.:

```yaml
wake:
  phrase: "hey assistant"
  model_path: "models/wake/hey_assistant.onnx"
```

## Changing the wake phrase

One command — the heavy data (features, RIRs, background, voice) is reused; only
synthetic clip generation re-runs:

```bash
bash training/train.sh --phrase "hey jarvis"          # full run
bash training/train.sh --phrase "athena" --smoke      # quick validation first
bash training/train.sh --phrase "friday" --name fri   # custom model-file name
```

This stamps a config from `wakeword.yml` (overriding only the phrase + model
name), trains, installs `models/wake/<name>.onnx`, and prints the `config.yaml`
lines. Each phrase gets its own clips/model, so runs never clobber each other.

**Pick the phrase well — this matters more than the tooling:**

- **2+ syllable phrases and distinctive names work best** ("Jarvis", "Sebastian",
  "Athena", "hey assistant"). The model keys on acoustic patterns, so there must
  be enough unique phonetic content.
- **Short, common single words false-trigger heavily** ("go", "now", "hey") —
  everyday speech trips them. A short name ("Sam", "Max") is also harder than a
  long one.
- For a **one-word trigger**, compensate in `wakeword.yml`: raise `n_samples`,
  lower `target_false_positives_per_hour`, and add similar-sounding words to
  `custom_negative_phrases`.
- espeak handles most names; verify pronunciation for unusual spellings with
  `espeak-ng "your word"`.

## Training a series of phrases

To train several wake words in one go — train, test, and commit each — list the
phrases in `training/phrases.txt` (one per line; blank lines and `#` comments
ignored) and run:

```bash
bash training/train_batch.sh                       # phrases from training/phrases.txt
bash training/train_batch.sh "jarvis" "athena"     # or phrases as args
bash training/train_batch.sh --smoke               # fast end-to-end dry run (tiny models)
bash training/train_batch.sh --no-commit           # train + test only, no commits
```

For each phrase it runs `train.sh`, then **gates** the model with `evaluate.py`:

- true-positive rate ≥ **90%**, false-positive rate ≤ **1%**, separation > **0**
  (positives' 10th percentile above backgrounds' 90th).
- **Pass** → record metrics in `models/wake/models.json` and make **one commit**
  for that model (`models/wake/<slug>.onnx` + the manifest).
- **Fail** → print why, **skip the commit**, and continue to the next phrase. The
  run exits non-zero if any phrase failed, and prints a summary table.

`models/wake/models.json` is the manifest of your trained series. Inspect it with:

```bash
python training/manifest.py list
```

The gate thresholds are flags on `evaluate.py` (`--min-tp`, `--max-fp`,
`--min-separation`) if you need to tune them; `train_batch.sh` evaluates at the
`config.yaml` wake threshold (0.6).

## Loading several phrases at once

The runtime can load a **series** of models so any of them wakes the assistant —
`wake.model_paths` in `config.yaml` (a list). Set it from the manifest:

```bash
python training/manifest.py select "hey assistant" jarvis   # by phrase or slug
```

This writes `wake.model_paths` into `config.yaml` (preserving comments) and
verifies the runtime reads exactly those. Restart the assistant; the boot log
lists every loaded model key, and speaking any of the phrases triggers a wake.

Equivalent without editing the file (e.g. for a one-off run):

```bash
ASSISTANT_WAKE__MODEL_PATHS='["models/wake/hey_assistant.onnx","models/wake/jarvis.onnx"]' \
  python -m assistant.app
```

Precedence: `model_paths` (the series) > `model_path` (single) > `model_name`
(stock `hey_jarvis` fallback). Each extra model adds a little CPU per audio
frame, so load the series you actually use.

## Costs / notes

- **Downloads (~18 GB):** 16 GB negative features, 255 MB Piper voice, ~170 MB
  validation set, plus RIR + AudioSet background audio. All resumable/idempotent.
- **Disk:** features + generated clips need ~25–30 GB free under `training/`.
- **Compute:** CPU is fine (the classifier is tiny). Clip generation is the long
  pole (~hours for a 20k full run). No GPU/CUDA required.
- **Everything under `training/data`, `training/work`, `training/.venv-train`, and
  the cloned generator is git-ignored** — only `wakeword.yml` and the scripts are tracked.

## Tuning

- `wakeword.yml` → `n_samples` (more positives = more robust, slower), `steps`,
  `target_false_positives_per_hour`, `custom_negative_phrases` (add real-world
  false triggers you observe). Changes here apply to every phrase you train.
- `setup_data.py --audioset-shards N` for more background variety (500 clips each).
- If it false-triggers or misses in your room, the highest-leverage fixes are
  raising `n_samples` and adding the offending phrases to `custom_negative_phrases`.
