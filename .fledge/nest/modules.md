---
generated: 2026-07-10T22:45:49Z
commit: ce70f988da5255908dc6a9bb3dc26206b5e57b36
agent: fledge-forager
fledge_version: 0.3.0
---

# Modules

Repo map of the directories `fledge scan` identified, one entry per module, as of the mid-restart state (commit `ce70f98`).

## root

Purpose: project bootstrap, active/reference configuration, packaging metadata, and CLAUDE.md guidance for the (currently absent) `assistant` runtime.

Key files: `pyproject.toml` (deps/extras/entry point), `config.yaml` + `default-config.yaml` (18-section runtime config schema), `Makefile` (`make release`/`make clean`), `.env.example` (secrets template), `.python-version` (3.12.13), `.gitignore`, `LICENSE` (AGPLv3), `CLAUDE.md`.

Look here for: what the runtime is supposed to do (config sections), how dependencies are sliced into extras, build/release commands, the secrets-vs-YAML split, Python/tooling pins.

## training

Purpose: self-contained wake-word ("Calcifer") training pipeline. Produces the `.onnx` model the runtime's wake detector consumes; fully synthetic (Piper VITS TTS + livekit-wakeword augmentation, no real recordings).

Key files: `training/README.md` (workflow phases), `training/bootstrap.sh` (idempotent ROCm venv builder), `training/calcifer.yaml` (production training config), `training/train.py` (single-model trainer), `training/train_batch.py` (sequential multi-phrase trainer), `training/manifest.py` (model registry / `models/wake/models.json` manager — also the only script that touches runtime `config.yaml`), `training/phrases.txt` (batch phrase list).

Look here for: how `calcifer.onnx` is produced and re-trained, the isolated `.venv-train` requirement (never share with runtime venv), how a trained model gets wired into `config.yaml` via `manifest.py select`, FPPH/recall/threshold tuning.

## models

Purpose: trained model artifacts consumed by the (absent) runtime's wake detector.

Key files: `models/wake/calcifer.onnx` (962952 bytes, trained ONNX wake-word detector), `models/wake/models.json` (metadata sidecar: phrase, fpph, recall, threshold, gate_passed, trained_at, model_path — keyed by model slug e.g. `"calcifer"`).

Look here for: what wake models exist and their trained metrics/thresholds; note `models/piper/*.onnx` (TTS voice, referenced by `config.yaml`/`default-config.yaml`) is NOT present in this repo — only the wake model is tracked (see `.gitignore`, which excludes `models/*` except `models/wake/*.onnx`).

## .github

Purpose: CI/release automation.

Key files: `.github/workflows/release.yml` — triggered on `v*` tags or manual dispatch; matrix build (`ubuntu-24.04` x86_64, `ubuntu-24.04-arm` aarch64, `fail-fast: false`) producing `dist/assistant-$(uname -m)` binaries, smoke-tested, then published to a GitHub Release.

Look here for: exact CI trigger conditions, build matrix, smoke-test steps, and the fact that this workflow currently depends on `packaging/build.sh`, which does not exist on disk (would fail today).

## pluma

Purpose: fledge's own planning scaffolding for this repo — where plumage (epics) and feathers (work units) will be authored. Currently empty except `.gitkeep` placeholders.

Key files: `pluma/plumage/.gitkeep`, `pluma/feathers/.gitkeep`.

Look here for: nothing yet — this is where future PLM-xxx/FTHR-xxx specs land as the project is planned via fledge.

## Not a scanned module: `.fledge/`

Fledge's own working state (skills, templates, this `nest/` context set). Not part of `fledge scan`'s module list (fledge's own infra), gitignored except skill definitions.

## Absent (referenced, not on disk)

`assistant/` (runtime package — entry point `assistant.app:main`), `tui/` (Textual monitor), `packaging/` (`build.sh`, invoked by `make release` and the release workflow). Do not assume these exist; confirm before editing or importing from them.
