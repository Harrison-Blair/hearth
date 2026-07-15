# Wake-word training (livekit-wakeword)

Trains the `.onnx` classifier the runtime wakes on
(`hearth/wake/livekit_detector.py`, `config.yaml` → `wake`). Default phrase:
**Calcifer**. The pipeline is [livekit-wakeword](https://github.com/livekit/livekit-wakeword):
one YAML (`calcifer.yaml`), one command, a conv-attention classifier head.

Fully synthetic, no recordings: livekit synthesizes positive + adversarial-negative
clips (Piper VITS), augments them with room reverb (MIT RIRs) and background noise
(MUSAN), extracts embeddings, and trains a classifier against ~2000 h of ACAV100M
negatives. Output: `training/output/<name>/<name>.onnx`.

Training runs in an **isolated venv** (`training/.venv-train`) so its torch/ROCm
stack never touches the hearth runtime. The runtime consumes only the exported
`.onnx`, so the two environments never share anything.

## 1. Bootstrap (one-time)

```bash
bash training/bootstrap.sh
```

Builds `.venv-train`: installs a **ROCm** torch for the AMD RX 9070 XT
(RDNA4/gfx1201) first, then `livekit-wakeword[train,eval,export]`, then asserts
torch sees the GPU. System deps (Arch): `espeak-ng libsndfile ffmpeg sox`.

> gfx1201 needs ROCm ≥ 6.4 wheels. If the `rocm6.4` index lacks RDNA4 kernels,
> point the `torch` install in `bootstrap.sh` at the newest ROCm index
> (`rocm6.5`/`7.x`). `HSA_OVERRIDE_GFX_VERSION` does **not** apply to RDNA4.

## 2. Smoke run (prove the plumbing)

```bash
training/.venv-train/bin/python training/train.py --smoke
```

Shrinks `calcifer.yaml` to a tiny fast run (~200 samples, 500 steps), writes
`models/wake/calcifer_smoke.onnx`, and records it in the manifest. The first run
triggers livekit `setup`, a **multi-GB download** (~16 GB ACAV100M features + MUSAN
backgrounds + RIRs + Piper voice) into `training/data`; pass `--skip-setup` on
re-runs. Livekit resumes a model's previous run from whatever is on disk; to start
over instead, pass `--fresh` (clears features/checkpoints/eval but keeps the
synthesized clips — the slow part) or `--fresh-clips` (wipes the model's whole
output dir for full regeneration). Don't use either while a run is live.
Inspect the result:

```bash
python training/manifest.py list                    # recall / fpph / thr per model
# training/output/calcifer_smoke/calcifer_smoke_det.png   # DET curve
python training/manifest.py select calcifer_smoke   # point config.yaml at it
```

## 3. Production run

```bash
training/.venv-train/bin/python training/train.py     # -> models/wake/calcifer.onnx
```

The full `calcifer.yaml` (25k samples, conv_attention/medium, 100k steps,
`target_fp_per_hour: 0.1`) — long-running on the GPU. When it finishes, set the
runtime threshold from the manifest's optimal threshold and select the model:

```bash
python training/manifest.py list                # note calcifer's `thr`
python training/manifest.py select calcifer     # writes config.yaml wake.model_paths
```

Then set `wake.threshold` in `config.yaml` to that value and restart the daemon.

## Training a series of phrases

To train several wake words in one pass, list them in `training/phrases.txt` (one
per line; blank lines and `#`-comments ignored) and run the **sequential** batch
trainer — one phrase at a time, each livekit run's stage output streamed live under
a `[i/N] <phrase>` header:

```bash
training/.venv-train/bin/python training/train_batch.py            # phrases.txt
training/.venv-train/bin/python training/train_batch.py "athena" "hey penguin"
training/.venv-train/bin/python training/train_batch.py --smoke    # quick plumbing per phrase
training/.venv-train/bin/python training/train_batch.py --n-samples 5000 --steps 20000  # cheap sweep
```

Each phrase derives its config from `calcifer.yaml` (dropping the Calcifer-specific
`custom_negative_phrases`, so livekit auto-generates each phrase's adversarial
negatives), trains into `models/wake/<slug>.onnx`, and records it in the manifest.
A failing phrase is reported and the batch continues; the run ends with the manifest
table. `--n-samples`/`--steps` (also on `train.py`) let you rank candidate phrases at
reduced scale before committing to a full run. Only the first phrase downloads data;
the rest reuse it.

## Tuning

`calcifer.yaml` knobs that matter most: `target_fp_per_hour` (the FPPH gate the
optimal threshold targets), `custom_negative_phrases` (add real-world false
triggers you observe — 1–2 phoneme edits from the wake word), `n_samples`
(more positives = more robust, slower), and `model.model_size`
(`small`/`medium`/`large`). `training/data`, `training/output`, `training/work`,
and `.venv-train` are git-ignored; only `calcifer.yaml` and the scripts are tracked.
