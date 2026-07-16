---
id: FTHR-021
title: "Vesta & Prometheus wake-word retrain"
plumage: PLM-006
status: hatching
priority: P1
depends_on: []
authored: 2026-07-16T02:44:46Z
agent: fledge-orchestrate/planning
fledge_version: 0.5.5
---

# FTHR-021: Vesta & Prometheus wake-word retrain

## Description
Retire "Calcifer" as a wake word entirely and replace it with two hand-curated, independently-trainable wake words, "Vesta" and "Prometheus," across the `training/` pipeline. Delivers all of PLM-006's criteria in one unit: renamed/authored configs, updated script defaults, a new manifest `remove` subcommand used to delete the legacy Calcifer artifact/entry, updated docs, and a smoke-run proof for both new phrases. Nothing in `hearth/` (the runtime) changes — confirmed no `wake` section exists in `config.yaml`/`default-config.yaml`.

## Affected Modules
- `training/calcifer.yaml` → renamed to `training/vesta.yaml`. See `.fledge/nest/data-model.md` → Training-pipeline on-disk formats for the full field list (data generation, TTS params, augmentation, model architecture, training hyperparameters).
- `training/prometheus.yaml` — new file, same schema/knobs as `vesta.yaml`.
- `training/train.py` — `--config` argument (currently defaults to `training/calcifer.yaml`) becomes required.
- `training/train_batch.py` — `BASE_CONFIG` constant (currently `training/calcifer.yaml`) repointed to `training/vesta.yaml`.
- `training/manifest.py` — add a `remove <slug>` subcommand (new `cmd_remove`, wired into the existing `argparse` subparser setup alongside `upsert`/`list`/`regen`/`select`).
- `training/test_manifest.py` — new file; unit tests for the `remove` subcommand, run by the normal repo-root `pytest` (no `.venv-train` needed — `manifest.py` is stdlib-only).
- `models/wake/calcifer.onnx` — deleted.
- `models/wake/models.json` — `"calcifer"` key removed (via the new `manifest.py remove` subcommand, not hand-edited).
- `README.md` — wake-word-specific lines only (see `.fledge/nest/domain.md`/architecture.md for how this file separates persona vs. wake-word mentions; PLM-005/FTHR-020 already handled the persona-character lines).
- `training/README.md` — instructions/examples referencing `calcifer.yaml`/"Calcifer" as the default phrase.
- **Not touched**: anything under `hearth/` (no `wake` module exists; confirmed no `wake` config section), `hearth/persona.py`, `config.yaml`/`default-config.yaml` (FTHR-020's territory).

## Approach
1. **Rename the base config**: `git mv training/calcifer.yaml training/vesta.yaml`. Update `model_name: calcifer` → `vesta`, `target_phrases: ["calcifer"]` → `["vesta"]`. Replace `custom_negative_phrases` (currently Calcifer-specific: calcify, lucifer, california, etc.) with a hand-curated list of 1-2-phoneme-edit near-misses for "vesta" (e.g. candidates like "vespa," "fiesta," "gesture," "Esther," "best a" — refine/expand based on judgment; the list should follow the existing file's comment convention: "1-2 phoneme edits from the wake word, not near-identical"). Update the file's header comment and the `# on = Calcifer character...`-style comments to reference Vesta. Leave every other knob (`n_samples`, TTS params, augmentation, `model.model_size`, training hyperparameters, `target_fp_per_hour`) unchanged — PLM-006 doesn't ask for tuning changes, only identity/negative-phrase changes.
2. **Author the Prometheus config**: copy `vesta.yaml`'s full structure into `training/prometheus.yaml`, set `model_name`/`target_phrases` to `prometheus`, and write a dedicated `custom_negative_phrases` list of Prometheus-appropriate near-misses (e.g. candidates like "promethium," "prometheum," "for me the us" — again, judgment-driven, matching the existing curation style). Same knob values as `vesta.yaml` otherwise (both wake words should get equivalent treatment; PLM-006 doesn't ask for divergent tuning).
3. **`train.py`**: change `ap.add_argument("--config", default=str(REPO / "training" / "calcifer.yaml"))` to drop the `default=` kwarg and add `required=True` (or equivalent — whatever `argparse` idiom cleanly makes it mandatory). Confirm `train.py --smoke` (no `--config`) now errors with a clear "required" message rather than silently defaulting.
4. **`train_batch.py`**: change `BASE_CONFIG = REPO / "training" / "calcifer.yaml"` to `BASE_CONFIG = REPO / "training" / "vesta.yaml"`. This only affects the (currently unused, by us) `phrases.txt` auto-derivation path — Vesta and Prometheus are trained via direct `train.py --config` invocations, not through this path, but the constant must stop pointing at a deleted file.
5. **`manifest.py` `remove` subcommand**: add `cmd_remove(a)` — `m = load(); existed = a.slug in m; m.pop(a.slug, None); save(m); print(f"manifest: removed {a.slug!r}" if existed else f"manifest: {a.slug!r} not found")` (no-op, not an error, when the slug isn't present — consistent with `cmd_regen`'s "safe to re-run" style elsewhere in this file). Wire it into the `argparse` subparsers the same way `upsert`/`list`/`regen`/`select` are wired (see the existing `ap = argparse.ArgumentParser(...)` block near the bottom of the file). Write `training/test_manifest.py` first (see Tests) pinning this behavior, confirm it fails against the unmodified file, then implement. Once passing, run `python training/manifest.py remove calcifer` and delete `models/wake/calcifer.onnx` directly (`rm` — no script manages `.onnx` file deletion, only the manifest entry).
6. **`README.md`**: update the wake-word-specific lines identified during interrogation (currently: "Wake word (Calcifer)" table cell, `models/wake/calcifer.onnx` path mentions, the "Wake word (**Calcifer**), STT, and TTS..." roadmap line) to name both "Vesta" and "Prometheus" and both `models/wake/vesta.onnx` / `models/wake/prometheus.onnx` paths. Leave the persona-character lines alone (FTHR-020 already updated those to Vesta).
7. **`training/README.md`**: update the "Default phrase: **Calcifer**" line and any example command referencing `calcifer.yaml` (bootstrap/smoke-run/production-run sections) to reflect the new file names and that there are now two dedicated configs, each run via its own `--config` flag.
8. **Smoke-run verification** (see Tests): run `training/.venv-train/bin/python training/train.py --smoke --config training/vesta.yaml` and the same for `training/prometheus.yaml`. If `.venv-train` doesn't exist yet, run `training/bootstrap.sh` first per `training/README.md`'s step 1. **Hard environment stop**: if bootstrap fails because this environment lacks the required ROCm/GPU stack (or any other environment-level blocker unrelated to the config content), STOP and escalate to the orchestrator with what was tried and what's needed — do not fake, skip, or weaken this verification step to force a pass.

## Tests
`training/` as a whole has no broader automated pytest suite (per `.fledge/nest/domain.md`'s own open questions: "No automated test suite exists for `training/`"), and the actual training pipeline is GPU/hardware-bound so its verification is the smoke-run's real output, not pytest. The one piece of pure, GPU-independent logic in this feather — the new `manifest.py remove` subcommand — gets a real automated unit test.

**Automated unit test** — `training/test_manifest.py` (new file, colocated with `manifest.py`; `manifest.py` is stdlib-only so this runs under the normal runtime `.venv` via a plain `pytest` from repo root, no `.venv-train` needed):
- `test_remove_existing_slug_deletes_entry` — write a temp `models.json`-shaped dict with 2+ entries (e.g. `calcifer` and one other), call the remove logic for `calcifer`, assert the `calcifer` key is gone and the other entry is untouched (same values).
- `test_remove_missing_slug_is_a_noop` — call remove for a slug not present in the dict; assert the dict is unchanged (no exception, no other entries affected) — pins the no-op-not-error behavior chosen in Approach step 5.
- Both tests exercise `manifest.py`'s `load`/`save`/new `cmd_remove` (or the underlying pop logic `cmd_remove` calls) against a `tmp_path`-redirected `models.json` (patch the module's `MANIFEST` path, mirroring how `hearth`'s own tests use `tmp_path` for isolation — see `.fledge/nest/testing.md` → Per-test isolation), not the real repo file.
- Implementation order (fixed): (1) write both tests against the unmodified `manifest.py` (no `remove` subcommand exists) and confirm they FAIL for the expected reason (`AttributeError`/`ImportError`/CLI-not-found, whichever the chosen call shape produces) — capture verbatim; (2) implement `cmd_remove`; (3) confirm both pass.

**Smoke-run verification** (real pipeline proof, not pytest — GPU/hardware-bound, per PLM-006's scope):
- **Before implementation** (i.e. against the current, unmodified `training/calcifer.yaml`/scripts): running `train.py --smoke --config training/vesta.yaml` and `--config training/prometheus.yaml` FAILS for the expected reason — those files don't exist yet (`FileNotFoundError` / argparse can't find the path). Capture this output verbatim as the "failing" evidence.
- **After implementation**: both smoke runs complete successfully (exit 0), produce `models/wake/vesta_smoke.onnx` and `models/wake/prometheus_smoke.onnx`, and `python training/manifest.py list` shows both `vesta_smoke` and `prometheus_smoke` entries. Capture this output as the "passing" evidence.
- Additionally verify: `python training/manifest.py list` no longer shows a `calcifer` entry after the `remove` step (real end-to-end use of the now-unit-tested subcommand); `ls models/wake/` no longer shows `calcifer.onnx`; `train.py --smoke` (no `--config` at all) now fails with an argparse "required" error (proves AC-4 without needing a full run).

## Acceptance Criteria
- [x] AC-1: Both `training/test_manifest.py`'s unit tests and the smoke-run verification in Tests were observed failing (for the expected reasons — no `remove` subcommand; missing config files) before implementation, and passing after.
- [x] AC-2: `training/vesta.yaml` exists with `model_name`/`target_phrases` = `vesta` and Vesta-specific curated negative phrases; `training/calcifer.yaml` no longer exists (satisfies PLM-006 AC-1/FC-1).
- [x] AC-3: `training/prometheus.yaml` exists with `model_name`/`target_phrases` = `prometheus`, its own curated negative phrases, and the same structure/knobs as `vesta.yaml` otherwise (satisfies PLM-006 AC-2/FC-2).
- [x] AC-4: `train.py --config` is required — running without it fails with a clear argparse error, no silent default (satisfies PLM-006 AC-3/FC-3).
- [x] AC-5: `train_batch.py`'s `BASE_CONFIG` resolves to `training/vesta.yaml` (satisfies PLM-006 AC-4/FC-4).
- [x] AC-6: `README.md` names both "Vesta" and "Prometheus" as wake words with both model paths; no remaining Calcifer wake-word reference (satisfies PLM-006 AC-5/FC-5).
- [x] AC-7: `training/README.md` has no remaining reference to `calcifer.yaml` or "Calcifer" as the default/example phrase (satisfies PLM-006 AC-6/FC-6).
- [x] AC-8: No occurrence of "calcifer"/"Calcifer" remains anywhere under `training/` or `models/wake/` (configs, scripts, docs, artifacts, manifest) (satisfies PLM-006 AC-8).
- [x] AC-9: `models/wake/calcifer.onnx` no longer exists on disk, `models/wake/models.json` has no `"calcifer"` key, and `manifest.py` has a working `remove <slug>` subcommand, covered by `training/test_manifest.py`'s two unit tests, used to perform the real removal (satisfies PLM-006 AC-9/FC-8).
- [x] AC-10: Full existing `pytest` suite (including the new `training/test_manifest.py`) passes with no other test broken.
