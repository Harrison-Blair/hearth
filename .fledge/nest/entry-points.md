---
generated: 2026-07-10T22:45:49Z
commit: ce70f988da5255908dc6a9bb3dc26206b5e57b36
agent: fledge-forager
fledge_version: 0.3.0
---

# Entry Points

How to run, build, and invoke this repo's tracked pieces today, plus the runtime entry point that's declared but not yet backed by code.

## Runtime (declared, not runnable today)

- **Python entry point** (`pyproject.toml:45`): `assistant = assistant.app:main` — the `assistant/` package is absent (mid-restart), so this entry point cannot currently be invoked.
- **Install**: `pip install -e '.[all]'` (every runtime capability except `aec`/`tui`) or `pip install -e '.[dev]'` (pytest, pytest-asyncio, ruff).
- **Config loading**: `pydantic-settings` loads `config.yaml`, overridable via `ASSISTANT_*` env vars (double-underscore nesting) and `.env` (secrets only).

## Dev commands (usable today, apply to whatever code exists)

- `pytest` — full suite, `asyncio_mode=auto` (no decorator needed for async tests).
- `pytest path/to/test_x.py::test_name` — single test.
- `ruff check .` — lint, line-length 100.

## Build & release

- `make release` — invokes `packaging/build.sh` (**absent on disk**); intended to produce `dist/assistant-$(uname -m)`, one native build per arch, no cross-compile.
- `make clean` — `rm -rf build dist .build-venv`.
- **CI** (`.github/workflows/release.yml`): triggers on `v*` tag push or manual `workflow_dispatch`; matrix job on `ubuntu-24.04` (x86_64) and `ubuntu-24.04-arm` (aarch64), `fail-fast: false`; builds, smoke-tests (`--version` + DEBUG-level import check), uploads artifacts (`artifacts/**/assistant-*`); release job (`if: startsWith(github.ref, 'refs/tags/')`) attaches both binaries to a GitHub Release via `softprops/action-gh-release@v2`.

## Wake-word training pipeline (`training/`, fully usable today)

- `bash training/bootstrap.sh` — one-time: builds isolated `training/.venv-train` (ROCm torch + livekit-wakeword), validates GPU usability.
- `training/.venv-train/bin/python training/train.py [--config <yaml>] [--smoke] [--skip-setup] [--fresh] [--fresh-clips] [--n-samples N] [--steps N]` — trains a single model. Default config `training/calcifer.yaml`; default output `models/wake/calcifer.onnx` (or `_smoke`-suffixed under `--smoke`).
- `training/.venv-train/bin/python training/train_batch.py [phrases...] [--smoke] [--skip-setup] [--n-samples N] [--steps N]` — sequential multi-phrase training; phrases default to `training/phrases.txt` or CLI args; outputs `models/wake/<slug>.onnx` per phrase; exits 1 if any phrase failed.
- `python training/manifest.py upsert <slug> --phrase "X" --eval <eval.json> [--target-fpph 0.1]` — records one trained model into `models/wake/models.json` (invoked automatically by `train.py`).
- `python training/manifest.py list` — prints the trained-model table (slug, phrase, recall%, fpph, threshold, gate pass/fail).
- `python training/manifest.py select <slug-or-phrase> [...]` — **the handoff to the runtime**: writes `config.yaml`'s `wake.model_paths`, then verifies via the (currently absent) runtime's `Config().wake.model_refs()`.
- `python training/manifest.py regen` — backfills manifest entries for any `models/wake/*.onnx` on disk not yet recorded.
- `ASSISTANT_WAKE__MODEL_PATHS='["models/wake/a.onnx"]'` — env-var override of wake model paths, no file edit needed.

## Open Questions

- No test files exist in the assigned scout scopes for `assistant/`/`tui/` (absent) — expect `pytest` to currently collect zero or near-zero tests until runtime code returns.
