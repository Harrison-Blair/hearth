---
generated: 2026-07-10T22:45:49Z
commit: ce70f988da5255908dc6a9bb3dc26206b5e57b36
agent: fledge-forager
fledge_version: 0.3.0
---

# Context Index

## architecture.md
Explains that this repo is mid-restart: the runtime (`assistant/`, `tui/`, `packaging/`) is absent from disk, and config/pyproject/CI reference it as intended design, not a working contract. Covers the intended voice-cascade pipeline (wake→recorder→stt→llm→agent→verify→persona→tts), how `training/` hands its `.onnx` output to the runtime via `manifest.py select`, and build/release/config architecture.
Read this when: orienting on how the pieces fit together, or before assuming any runtime file exists.

## modules.md
Repo map of the six modules `fledge scan` found (root, training, models, .github, pluma) plus a note on what's absent (`assistant/`, `tui/`, `packaging/`). Each entry lists purpose, key files, and "look here for" pointers.
Read this when: deciding which directory/file to open first for a given task.

## conventions.md
Reconciled conventions: config-as-code/Pi-portability philosophy, the FTHR-015 secrets-in-`.env`-only rule, `ASSISTANT_*` double-underscore env nesting, per-phase optional dependencies with pin rationale, per-arch native builds, Python/ruff/pytest pins, training/runtime venv isolation, and the fledge commit-message taxonomy.
Read this when: writing config, adding a dependency, naming an env var, or making a commit and unsure of the expected format.

## data-model.md
The `config.yaml`/`default-config.yaml` 18-section schema (values and meaning per section — no Pydantic classes exist on disk to cite instead), the `.env.example` secrets schema, `training/calcifer.yaml`'s training-config schema, and `models/wake/models.json`'s registry schema.
Read this when: adding/changing a config field, a secret, a training parameter, or the model registry format.

## dependencies.md
Deduplicated external dependencies across runtime `pyproject.toml` extras, external services (OpenRouter, Ollama, Tavily, Exa, Open-Meteo, Google Calendar), the isolated training pipeline (ROCm torch, livekit-wakeword, Piper VITS), and CI actions — each with a usage note and, where relevant, why a pin exists.
Read this when: adding a new capability/extra, wiring up an external service, or debugging a dependency/build issue.

## entry-points.md
How to run things today: dev commands (pytest, ruff), the declared-but-unbacked `assistant.app:main` entry point, `make release`/CI build flow (blocked on absent `packaging/build.sh`), and the full training pipeline command set (`bootstrap.sh`, `train.py`, `train_batch.py`, `manifest.py` subcommands) including the `manifest.py select` handoff into `config.yaml`.
Read this when: trying to actually run, build, or train something in this repo.

## testing.md
States plainly that no test files exist anywhere in the tracked tree (consistent with the absent runtime), documents the `pytest`/`asyncio_mode=auto`/ruff setup that's configured but has nothing to run yet, and describes the training pipeline's `--smoke`-flag/gate-based quality checks in place of unit tests.
Read this when: asked to add tests, or judging whether "run the tests" will do anything meaningful right now.

## domain.md
Glossary spanning two domains: the voice-assistant product (Calcifer, wake word, VAD, barge-in, AEC, persona/revoice, verify loop, FPPH/recall/gate/slug/manifest from training) and the fledge development process (plumage/feather/fledged/molt evidence/forager/scout/nest).
Read this when: an unfamiliar term (product or process) appears and needs a precise definition.

## Coverage limits

- Runtime source (`assistant/`, `tui/`, `packaging/`) does not exist on disk — all runtime behavior described here is inferred from config values, `pyproject.toml`, and CLAUDE.md, not from code.
- `models/wake/calcifer.onnx` is a binary artifact; scouted for size/location only, not content.
- No test files exist anywhere in the tracked tree.
