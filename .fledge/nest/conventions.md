---
generated: 2026-07-10T22:45:49Z
commit: ce70f988da5255908dc6a9bb3dc26206b5e57b36
agent: fledge-forager
fledge_version: 0.3.0
---

# Conventions

Coding, configuration, and process conventions observed across the tracked files, reconciled where scouts overlapped.

## Config-as-code / config-driven Pi port

Every device id, model path, and threshold is config-driven (CLAUDE.md) so the eventual Raspberry Pi 5 port is meant to be config-only, not code changes. `default-config.yaml` documents each knob inline (VAD aggressiveness, thresholds, Pi tuning notes) — read it, not just `config.yaml`, to understand what a setting does.

## Secrets separation (FTHR-015 rule)

Hard rule: API keys live in `.env` **only**, via `ASSISTANT_<SECTION>__<PROVIDER>_API_KEY` (see `.env.example`: `ASSISTANT_LLM__OPENROUTER_API_KEY`, `ASSISTANT_LLM__OPENCODE_ZEN_API_KEY`, `ASSISTANT_WEB_SEARCH__TAVILY_API_KEY`, `ASSISTANT_WEB_SEARCH__EXA_API_KEY`). Non-secret tunables (models, hosts, thresholds) stay in `config.yaml`/`default-config.yaml`. **Never add secret fields to the YAML files.**

## Env var override nesting

`ASSISTANT_*` env vars nest with a double underscore: `ASSISTANT_LLM__MODEL`, `ASSISTANT_LOGGING__LEVEL`. Same double-underscore convention used for the `.env` secret keys above.

## Per-phase optional dependencies

`pyproject.toml` slices dependencies into per-capability extras (`tts`, `wake`, `stt`, `vad`, `llm`, `nlu`, `scheduling`, `search`, `gcal`, plus `aec` and `tui` which are **deliberately excluded** from the `all` meta-extra) so each capability installs and can fail independently. Comments in `pyproject.toml` record *why* specific pins exist — read them before touching deps:
- `vad` pins `setuptools<81` because `webrtcvad` imports `pkg_resources`, removed in setuptools 81+.
- `tui` pins `textual~=8.2` because internals (RichLog) were verified against 8.2.7 specifically.
- `aec` and `tui` are excluded from `all` because they're native/build-sensitive; the app is expected to degrade gracefully (e.g. AEC passthrough) when their imports fail.

## Per-architecture native builds, no cross-compile

`make release` (and the CI release workflow) build a single-file binary once per target arch (x86_64, aarch64) natively — there is no cross-compilation. Output convention: `dist/assistant-$(uname -m)`.

## Python / tooling pins

- Python pinned to 3.12 (`.python-version`: `3.12.13`); note `pyproject.toml`'s `requires-python` is looser (`>=3.11`) — `.python-version` is the enforced pin for this repo.
- `ruff check .`, line-length 100 (`pyproject.toml`).
- `pytest`, `asyncio_mode=auto` — async tests need no `@pytest.mark.asyncio` decorator.

## Training/runtime venv isolation

`training/.venv-train` (ROCm torch + livekit-wakeword) must **never** be shared with or merged into the runtime venv. The runtime is only ever meant to consume the exported `.onnx` artifact plus `models/wake/models.json` metadata — never a training-time dependency.

## Training pipeline conventions (training/)

- Fully synthetic data: Piper VITS-generated positive/adversarial clips, no real recordings.
- Slug derivation: `manifest.slug()` = `re.sub(r"[^a-z0-9]+", "_", phrase.lower()).strip("_")` (`training/manifest.py`).
- Model naming: `model_name` in a training config becomes `models/wake/{model_name}.onnx`; a `_smoke` suffix is reserved and load-bearing (referenced by a `tui.discovery.clean_smoke_models` — in the absent `tui/` — per a comment in `training/train.py`).
- Batch training (`train_batch.py`) is sequential, not parallel; the first phrase downloads shared data, later phrases reuse it (`skip_setup=i>0`); phrase-specific fields like `custom_negative_phrases` are dropped for auto-generated phrases; failures are caught per-phrase and the batch still runs to completion, exiting 1 overall if any phrase failed.
- `manifest.py select` writes `config.yaml` and then verifies the round-trip via the runtime's `Config().wake.model_refs()` — this call currently cannot execute since `assistant/` is absent.

## Fledge process taxonomy in commit messages

Match fledge's taxonomy in commits (see `domain.md` for full glossary): `PLM-xxx` (plumage epic), `FTHR-xxx` (feather unit with numbered ACs), `FTHR-xxx: fledged` (complete, ACs verified), `review: verify FTHR-xxx AC-1..N` / `review: uncheck AC-N …` (reviewer pass), test-first commits (`FTHR-xxx: test-first — … tests`).

## Sidecar metadata pattern

Trained model artifacts follow a binary + JSON sidecar pattern: `models/wake/calcifer.onnx` (binary) alongside `models/wake/models.json` (metrics: `fpph`, `recall`, `threshold`, `gate_passed`, `trained_at`, `model_path`, `phrase`, keyed by model slug) — metrics travel with the artifact for auditing/selection rather than living only in training logs.

## Open Questions

- Is the `setuptools<81` pin expected to lift once `webrtcvad` updates, or is it a long-term constraint?
- Will `pluma/` conventions (spec format, naming) be established once the first plumage/feather is authored, or does fledge's own tooling enforce them uniformly?
