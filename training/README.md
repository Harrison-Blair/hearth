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

This stamps a config from `wakeword.yml` (overriding the phrase + model name),
trains, installs `models/wake/<name>.onnx`, and prints the `config.yaml` lines.
Each phrase gets its own clips/model, so runs never clobber each other.

**Pick the phrase well — this matters more than the tooling:**

- **2+ syllable phrases and distinctive names work best** ("Jarvis", "Sebastian",
  "Athena", "hey assistant"). The model keys on acoustic patterns, so there must
  be enough unique phonetic content.
- **Short, common single words false-trigger heavily** ("go", "now", "hey") —
  everyday speech trips them. A short name ("Sam", "Max") is also harder than a
  long one.
- A **one-word trigger is auto-optimized for accuracy** by `make_config.py`: it
  raises `n_samples`, lowers `target_false_positives_per_hour`, and seeds
  `custom_negative_phrases` with the plural plus CMU-dictionary soundalikes (real
  words that sound similar, to suppress false accepts). Soundalikes need the
  training-only `pronouncing` dep (installed by `bootstrap.sh`); without it you
  still get the plural plus openWakeWord's built-in phoneme-overlap negatives.
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
bash training/train_batch.sh --stream "penguin"    # tee full train/eval output live
```

By default the per-phrase `train.sh` + `evaluate.py` output is hidden behind the
live table (it goes to `training/work/<slug>.train.log`). Pass **`--stream`** to
tee that output to the terminal instead — you see the Stage-1 synth ETA, training
progress, and the eval distribution/gate live. Best for a single phrase, where the
table is overkill; for a multi-phrase run the interleaved output is noisy, so
prefer `tail -f training/work/<slug>.train.log` per phrase there.

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

## Going faster (parallelism)

Clip synthesis (Stage 1) is the long pole, and by default openWakeWord runs it in
a single process. Both scripts take `--jobs N` to use a budget of **N cores**:

```bash
bash training/train.sh --phrase "athena" --jobs 16     # one phrase, 16 cores
bash training/train_batch.sh --jobs 4 phrases.txt      # 4 phrases at a time
```

- **`train.sh --jobs N`** shards Stage 1 across N worker processes and runs
  Stages 2–3 (features/train) on N threads. It also logs a live **ETA**
  (`Stage 1: 6300/44000 clips (14%) · 12.4 clips/s · ~51m left`) and the total
  Stage-1 time when done. Default `N` = `$WW_JOBS` or `nproc`.
- **`train_batch.sh --jobs P`** trains P phrases concurrently, splitting the
  `$WW_CORES` (default `nproc`) budget so each phrase gets `nproc/P` cores. With
  the default `--jobs 1` a single phrase gets the whole budget (cap it with
  `WW_CORES=N` if memory is tight). Commits are serialized after the wave (one per
  model, in input order); per-phrase output goes to
  `training/work/<slug>.train.log` unless you pass `--stream`.
- Quality is unchanged — `n_samples` and every clip count stay the same; this is
  pure parallelism, not a sample-count trade-off.
- **Memory** is the limit: each synth worker loads its own ~255 MB Piper voice, so
  `--jobs 16` needs ~10–14 GB RAM. Lower `--jobs` if you hit pressure.
- `--jobs 1` is the original single-process behavior (unchanged). The core-budget
  patch that lets Stages 2–3 use all cores is applied by `bootstrap.sh`; if you
  bootstrapped before this change, re-run it (idempotent) to pick it up.

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
  pole (~hours for a 20k full run on one core) — use `--jobs N` to spread it
  across cores (see "Going faster"). No GPU/CUDA required.
- **Everything under `training/data`, `training/work`, `training/.venv-train`, and
  the cloned generator is git-ignored** — only `wakeword.yml` and the scripts are tracked.

## Tuning

- `wakeword.yml` → `n_samples` (more positives = more robust, slower), `steps`,
  `target_false_positives_per_hour`, `custom_negative_phrases` (add real-world
  false triggers you observe). These are the baseline for every phrase; a
  single-word phrase additionally auto-tunes `n_samples`,
  `target_false_positives_per_hour`, and `custom_negative_phrases` (see
  "Changing the wake phrase").
- `setup_data.py --audioset-shards N` for more background variety (500 clips each).
- If it false-triggers or misses in your room, the highest-leverage fixes are
  raising `n_samples` and adding the offending phrases to `custom_negative_phrases`.
