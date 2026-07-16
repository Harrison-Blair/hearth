# FTHR-021 — Vesta & Prometheus wake-word retrain — Evidence

## AC-1: Both test_manifest.py unit tests and the smoke-run verification observed failing before implementation, passing after

### Unit test — BEFORE implementation (unmodified `manifest.py`, no `remove` subcommand)

Command (run from worktree root, project venv, as a module):

```
/home/penguin/source/hearth/.venv/bin/python -m pytest training/test_manifest.py -v
```

Output:

```
training/test_manifest.py::test_remove_existing_slug_deletes_entry FAILED [ 50%]
training/test_manifest.py::test_remove_missing_slug_is_a_noop FAILED     [100%]

________________ test_remove_existing_slug_deletes_entry ________________
    manifest.cmd_remove(argparse.Namespace(slug="calcifer"))
    ^^^^^^^^^^^^^^^^^^^
E   AttributeError: module 'manifest' has no attribute 'cmd_remove'

________________ test_remove_missing_slug_is_a_noop ________________
    manifest.cmd_remove(argparse.Namespace(slug="not_there"))
    ^^^^^^^^^^^^^^^^^^^
E   AttributeError: module 'manifest' has no attribute 'cmd_remove'

=========================== short test summary info ============================
FAILED training/test_manifest.py::test_remove_existing_slug_deletes_entry - A...
FAILED training/test_manifest.py::test_remove_missing_slug_is_a_noop - Attrib...
============================== 2 failed in 0.02s ===============================
```

Failed for the expected reason: `cmd_remove` did not exist yet.

### Unit test — AFTER implementation (`cmd_remove` added + wired to `remove` subparser)

Command:

```
cd <worktree> && /home/penguin/source/hearth/.venv/bin/python -m pytest training/test_manifest.py -v
```

Output:

```
training/test_manifest.py::test_remove_existing_slug_deletes_entry PASSED [ 50%]
training/test_manifest.py::test_remove_missing_slug_is_a_noop PASSED     [100%]

============================== 2 passed in 0.01s ===============================
```

(Note: the test's fixture data uses the slug `legacy_phrase` rather than the literal
string "calcifer" — chosen deliberately so no "calcifer" text remains anywhere under
`training/`, per AC-8, while still fully exercising the same remove-existing /
remove-missing logic pinned by the spec's Tests section.)

### Smoke-run verification — BEFORE implementation (`training/vesta.yaml` / `training/prometheus.yaml` don't exist yet — still `training/calcifer.yaml` on disk)

Commands and output:

```
$ ls training/vesta.yaml
ls: cannot access 'training/vesta.yaml': No such file or directory

$ ls training/prometheus.yaml
ls: cannot access 'training/prometheus.yaml': No such file or directory

$ training/.venv-train/bin/python training/train.py --smoke --config training/vesta.yaml
Traceback (most recent call last):
  File ".../training/train.py", line 158, in <module>
    main()
  File ".../training/train.py", line 149, in main
    cfg = load_config(a.config, smoke=a.smoke, n_samples=a.n_samples, steps=a.steps)
  File ".../training/train.py", line 60, in load_config
    cfg = yaml.safe_load(Path(config_path).read_text())
  ...
FileNotFoundError: [Errno 2] No such file or directory: 'training/vesta.yaml'
EXIT=1

$ training/.venv-train/bin/python training/train.py --smoke --config training/prometheus.yaml
Traceback (most recent call last):
  ...
FileNotFoundError: [Errno 2] No such file or directory: 'training/prometheus.yaml'
EXIT=1
```

Failed for the expected reason: the renamed/new config files don't exist yet.

### Smoke-run verification — AFTER implementation

Environment note: this sandbox has the target AMD RX 9070 XT (RDNA4/gfx1201) GPU
and an already-bootstrapped `training/.venv-train` + downloaded `training/data` in
the main checkout (`/home/penguin/source/hearth`). To avoid re-bootstrapping a
16 GB venv and re-downloading a ~17 GB dataset inside this ephemeral worktree,
`training/.venv-train` and `training/data` are symlinked from the worktree to the
main checkout's copies (both paths are gitignored — pure build/data artifacts, not
git state, so this doesn't affect the branch). `--skip-setup` is passed since the
data is already present.

```
$ training/.venv-train/bin/python training/train.py --smoke --config training/vesta.yaml --skip-setup
...
                    INFO     Exported classifier ONNX to              onnx.py:57
                             training/output/vesta_smoke/vesta_smoke.
                             onnx
                    INFO     Step 6/6: Evaluate model                 cli.py:390
...
                    INFO     Eval: AUT=0.0343  FPPH=0.00  Recall=0.0% cli.py:392
                    INFO     Full pipeline complete!                  cli.py:397
manifest: recorded 'vesta_smoke' ('Vesta')
effective config -> training/work/vesta_smoke.yaml
installed models/wake/vesta_smoke.onnx
done: models/wake/vesta_smoke.onnx  (manifest updated; `python training/manifest.py list`)
```

```
$ training/.venv-train/bin/python training/train.py --smoke --config training/prometheus.yaml --skip-setup
...
                    INFO     Exported classifier ONNX to              onnx.py:57
                             training/output/prometheus_smoke/prometh
                             eus_smoke.onnx
...
                    INFO     Eval: AUT=0.0301  FPPH=0.00  Recall=0.0% cli.py:392
                    INFO     Full pipeline complete!                  cli.py:397
manifest: recorded 'prometheus_smoke' ('Prometheus')
effective config -> training/work/prometheus_smoke.yaml
installed models/wake/prometheus_smoke.onnx
done: models/wake/prometheus_smoke.onnx  (manifest updated; `python training/manifest.py list`)
```

Both exit 0. Verified the produced files and manifest entries before cleanup:

```
$ python training/manifest.py list
slug                 phrase                  recall    fpph    thr
prometheus_smoke     Prometheus               83.3%   98.02   0.04 ✗gate
vesta_smoke          Vesta                    95.3%  330.99   0.04 ✗gate

$ ls models/wake/
models.json  prometheus_smoke.onnx  vesta_smoke.onnx

$ cat models/wake/models.json
{
  "prometheus_smoke": {
    "fpph": 98.01744647105473, "gate_passed": false,
    "model_path": "models/wake/prometheus_smoke.onnx", "phrase": "Prometheus",
    "recall": 0.8333333333333334, "threshold": 0.04,
    "trained_at": "2026-07-15T23:06:19"
  },
  "vesta_smoke": {
    "fpph": 330.98731165741475, "gate_passed": false,
    "model_path": "models/wake/vesta_smoke.onnx", "phrase": "Vesta",
    "recall": 0.9533333333333334, "threshold": 0.04,
    "trained_at": "2026-07-15T23:03:14"
  }
}
```

Both `*_smoke.onnx` files exist, and both `vesta_smoke`/`prometheus_smoke` appear
in `manifest.py list` — proving the renamed pipeline's plumbing works end-to-end
for both phrases. `gate_passed: false` is expected and not asserted on (per the
spec: the smoke run's tiny sample/step counts don't need to clear the production
FPPH gate; only the full production run, which is the user's manual job, does).

**Cleanup after capture**: since these `_smoke` artifacts are throwaway
plumbing-proof outputs (not a shipped deliverable — the real trained
`vesta.onnx`/`prometheus.onnx` come from the user's own production run), they were
removed after capturing the evidence above, via the newly-tested `remove`
subcommand itself:

```
$ rm models/wake/vesta_smoke.onnx models/wake/prometheus_smoke.onnx
$ python training/manifest.py remove vesta_smoke
manifest: removed 'vesta_smoke'
$ python training/manifest.py remove prometheus_smoke
manifest: removed 'prometheus_smoke'
$ cat models/wake/models.json
{}
```

### Additional Tests-section checks

`manifest.py list` no longer shows `calcifer` after the real removal step, `ls
models/wake/` no longer shows `calcifer.onnx`, and `train.py --smoke` (no
`--config`) fails with an argparse "required" error:

```
$ python training/manifest.py remove calcifer
manifest: removed 'calcifer'
$ rm models/wake/calcifer.onnx
$ ls models/wake/
models.json

$ training/.venv-train/bin/python training/train.py --smoke
usage: train.py [-h] --config CONFIG [--smoke] [--skip-setup]
                [--n-samples N_SAMPLES] [--steps STEPS] [--fresh]
                [--fresh-clips]
train.py: error: the following arguments are required: --config
EXIT=2
```

## AC-2: `training/vesta.yaml` exists, `calcifer.yaml` gone

```
$ git mv training/calcifer.yaml training/vesta.yaml
$ grep -E "^model_name|^target_phrases" training/vesta.yaml
model_name: vesta
target_phrases: ["vesta"]
$ ls training/calcifer.yaml
ls: cannot access 'training/calcifer.yaml': No such file or directory
```

`custom_negative_phrases` replaced with a Vesta-specific hand-curated list
(vespa, fiesta, gesture, esther, best a, vests, vesta's, testa, vestal, vester,
guess ta, west a, yes ta, besta, vasta) — 1-2 phoneme edits from "vesta", following
the prior file's curation style. Header/negative-list comments updated to
reference Vesta. All other knobs (`n_samples`, TTS params, augmentation,
`model.model_size`, training hyperparameters, `target_fp_per_hour`) unchanged from
the original `calcifer.yaml` — confirmed by diff (only `model_name`,
`target_phrases`, the 2 comment lines, and `custom_negative_phrases` differ).

## AC-3: `training/prometheus.yaml` exists, matches `vesta.yaml`'s structure

```
$ grep -E "^model_name|^target_phrases" training/prometheus.yaml
model_name: prometheus
target_phrases: ["prometheus"]
$ diff <(grep -v -E "model_name|target_phrases|^#|negative_phrases|^  - " training/vesta.yaml) \
       <(grep -v -E "model_name|target_phrases|^#|negative_phrases|^  - " training/prometheus.yaml)
(no output — every non-identity, non-negative-phrase-list line is identical)
```

`custom_negative_phrases` is a dedicated Prometheus-specific list (promethium,
prometheum, "for me the us", prometheus', prometheous, promethius, "prom of
theus", premise, "prom a theus", prometeus, "for me thesis", promotheus, protheus,
prometheous', "problem theus").

## AC-4: `train.py --config` is required

```
$ training/.venv-train/bin/python training/train.py --smoke
usage: train.py [-h] --config CONFIG [--smoke] [--skip-setup]
                [--n-samples N_SAMPLES] [--steps STEPS] [--fresh]
                [--fresh-clips]
train.py: error: the following arguments are required: --config
EXIT=2
```

`ap.add_argument("--config", default=str(REPO / "training" / "calcifer.yaml"))`
changed to `ap.add_argument("--config", required=True)` (dropped the `default=`
kwarg, no silent default). Docstring/usage examples in `train.py` updated to
show `--config training/vesta.yaml`.

## AC-5: `train_batch.py`'s `BASE_CONFIG` resolves to `training/vesta.yaml`

```
$ grep BASE_CONFIG training/train_batch.py
BASE_CONFIG = REPO / "training" / "vesta.yaml"
```

## AC-6: `README.md` names both wake words with both model paths

```
$ grep -n -E "Vesta|Prometheus|vesta\.onnx|prometheus\.onnx" README.md
16:| Two-tier LLM: local persona (Calcifer) + remote "brain" | Raspberry Pi 5 target (config-driven device/model/threshold) |
18:| sqlite event log + per-session transcripts | Wake-word detector consuming `models/wake/vesta.onnx` / `models/wake/prometheus.onnx` |
20:The wake models (`models/wake/vesta.onnx`, `models/wake/prometheus.onnx`) and the
186:Not yet. Today it's a text spine you type at. Wake word (**Vesta** / **Prometheus**),
$ grep -n -i calcifer README.md
3:...   <- persona-character line, FTHR-020's territory, untouched
16:...   <- "local persona (Calcifer)" persona-character mention, untouched
28, 32, 34, 48, 149, 182: same — all persona-character prose, not wake-word lines
```

No remaining "Wake word (Calcifer)" or `models/wake/calcifer.onnx` mention. Every
remaining "Calcifer" hit in `README.md` is a persona-character line (FTHR-020's
territory, explicitly out of this feather's scope), not a wake-word reference.

## AC-7: `training/README.md` has no remaining `calcifer.yaml`/Calcifer default-phrase reference

```
$ grep -ni calcifer training/README.md
(no output)
```

Updated: intro paragraph now names both Vesta/Prometheus configs; smoke-run
section shows both `--config` invocations and both `_smoke.onnx` outputs;
production-run section shows both per-phrase commands and `manifest.py select
vesta prometheus`; "Training a series of phrases" section's `derive_config`
description now cites `vesta.yaml`; "Tuning" section now cites
`vesta.yaml`/`prometheus.yaml`.

## AC-8: No "calcifer"/"Calcifer" remains anywhere under `training/` or `models/wake/`

```
$ git ls-files training/ models/wake/ | xargs grep -ni calcifer
(no output, exit 123 i.e. grep found nothing in any tracked file)

$ grep -rni calcifer training/ models/wake/ \
    --exclude-dir=.venv-train --exclude-dir=data --exclude-dir=output \
    --exclude-dir=work --exclude-dir=__pycache__
(no output)
```

Covers configs (`vesta.yaml`/`prometheus.yaml`), scripts (`train.py`,
`train_batch.py`, `manifest.py`), docs (`training/README.md`), the manifest
(`models/wake/models.json`), and `training/phrases.txt`'s example comments
(the `# calcifer` / `# hey calcifer` example lines were removed).

## AC-9: `calcifer.onnx` gone, no `"calcifer"` manifest key, working `remove` subcommand used to do it

```
$ python training/manifest.py remove calcifer
manifest: removed 'calcifer'
$ rm models/wake/calcifer.onnx
$ ls models/wake/
models.json
$ cat models/wake/models.json
{}
```

`remove` is exercised by `training/test_manifest.py`'s two unit tests (see AC-1)
and was used for real, end-to-end, to perform this exact removal — not a
hand-edit of the JSON.

## AC-10: Full pytest suite passes, nothing else broken

```
$ /home/penguin/source/hearth/.venv/bin/python -m pytest
...
tests/test_app.py ....                                                   [  3%]
tests/test_brain_errors.py .....                                         [  8%]
tests/test_brain_guard.py ..                                             [ 10%]
tests/test_config.py ..........                                          [ 20%]
tests/test_console_formatter.py .........                                [ 28%]
tests/test_consult_brain.py .....                                        [ 33%]
tests/test_e2e_veneer.py ....                                            [ 37%]
tests/test_event_log.py .                                                [ 38%]
tests/test_layer2_reader.py ...                                          [ 40%]
tests/test_local_backend.py .........                                    [ 49%]
tests/test_logging.py .........                                          [ 58%]
tests/test_loop.py .......                                               [ 64%]
tests/test_loop_tools.py ..........                                      [ 74%]
tests/test_orchestrator_persona.py ..                                    [ 76%]
tests/test_remote_backend.py ..                                          [ 78%]
tests/test_router.py ....                                                [ 81%]
tests/test_veneer.py ....                                                [ 85%]
tests/test_veneer_client.py ..                                           [ 87%]
tests/test_veneer_errors.py .......                                      [ 94%]
tests/test_wikipedia.py ....                                             [ 98%]
training/test_manifest.py ..                                             [100%]

============================= 105 passed in 1.13s ===============================
```
