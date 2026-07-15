---
generated: 2026-07-15T22:30:28Z
commit: a8489b1afa55662a54ba66548a2e176584a3f387
agent: fledge-forager
fledge_version: 0.5.4
---

# Modules

Repo map: one entry per module scanned by `fledge scan`, its purpose, its key files, and where to look for what.

## `<root>`

**Purpose:** Project configuration, documentation, dependency spec, and build entry point for the `hearth` distribution.

**Key files:** `pyproject.toml` (package metadata, 12 optional extras, `hearth = hearth.app:main` entry point), `config.yaml` (active config), `default-config.yaml` (documented reference config), `.env.example` (secret template), `CLAUDE.md` (dev guidance), `README.md` (quickstart/FAQ), `MANUAL_SMOKE.md` (manual live-service test procedure), `Makefile` (`make release`/`make clean`), `.python-version` (3.12.13), `LICENSE` (AGPL v3), `.gitignore`.

**Look here for:** what config knobs exist and what they mean (`default-config.yaml`), how secrets vs. tunables are split (`CLAUDE.md`, `.env.example`), how to build/release (`Makefile` → `packaging/`), dependency extras (`pyproject.toml`).

## `hearth`

**Purpose:** The runtime Python package — the daemon that implements the text/LLM spine of the voice assistant: WebSocket veneer → ReAct orchestration loop → two-tier LLM routing → tool dispatch → event logging.

**Key files:**
- `hearth/app.py` — CLI entry (`main`), async daemon startup (`_run_daemon`), wires every subsystem together.
- `hearth/config.py` — `Settings` (pydantic-settings), config precedence and secret resolution.
- `hearth/loop.py` — `Loop.run_turn()` (top-level orchestrator) and `run_react_rounds()` (shared ReAct engine used by both the orchestrator and nested brain consult).
- `hearth/brain/` — `base.py` (Brain protocol, Message/ToolCall/ToolSpec/BrainResult), `router.py` (tier→backend selection), `local.py`/`remote.py` (backend implementations), `openai_compat.py` (shared OpenAI-style `/chat/completions` client), `errors.py` (`BrainError`).
- `hearth/tools/` — `registry.py` (ToolRegistry), `consult.py` (`BrainConsult`, the nested ReAct tool), `wikipedia.py` (the one implemented data tool).
- `hearth/veneer/` — `server.py` (WebSocket daemon loop), `protocol.py` (wire format + serialization whitelist), `client.py` (stdin/stdout reference client).
- `hearth/memory/` — `log.py` (append-only SQLite `EventLog`), `reader.py` (`EventReader` cursor), `consumer.py` (future Layer2Consumer seam, not implemented).
- `hearth/events.py` (`ToolActivity`, `EventSink`), `hearth/transcript.py` (best-effort transcript writer), `hearth/persona.py` (no-op `restyle()` stub), `hearth/logging_setup.py` (idempotent logging setup).

**Look here for:** the actual runtime behavior of every turn — routing, tool-calling, error handling, logging, the WebSocket contract. This is the module every feature touches.

## `tests`

**Purpose:** Hermetic pytest suite (60+ tests, 19 files) covering config precedence, both LLM backends, tier routing, the ReAct loop, nested brain-consult, the veneer WebSocket boundary, event logging, and the wikipedia tool — all via `httpx.MockTransport` / `websockets` test doubles, no live services.

**Key files:** `conftest.py` (shared fixtures: `llm_config`, `two_tier_llm_config`, `canned_completion`, `HostRouter`), `test_e2e_veneer.py` (full-stack integration), `test_router.py`, `test_loop.py`/`test_loop_tools.py`, `test_consult_brain.py`/`test_brain_guard.py`, `test_veneer.py`/`test_veneer_errors.py`, `test_brain_errors.py`, `test_config.py`, `test_event_log.py`/`test_layer2_reader.py`, `test_wikipedia.py`.

**Look here for:** expected behavior/contracts for any `hearth/` module (each test file mirrors a source module), and the pattern for hermetic async test doubles (`HostRouter`, `_FakeWebSocket`, etc.) to follow when adding tests.

## `training`

**Purpose:** Fully synthetic wake-word model training pipeline (livekit-wakeword + Piper TTS + MUSAN/RIR augmentation), producing `.onnx` classifiers for `models/wake/`. Runs in an isolated `training/.venv-train` (ROCm torch) that never shares packages with the runtime venv.

**Key files:** `train.py` (`run_training()`, single-model CLI, `--smoke` fast-path), `train_batch.py` (sequential multi-phrase driver, reuses the ~16 GB one-time data download), `manifest.py` (registry CLI: `upsert`/`list`/`regen`/`select`; writes `models/wake/models.json` and patches `config.yaml` `wake.model_paths`), `calcifer.yaml` (production training config), `phrases.txt` (batch phrase list), `bootstrap.sh` (builds `.venv-train`), `README.md` (full workflow doc).

**Look here for:** how a new wake word gets trained and how a trained model gets wired into `config.yaml` (`manifest.py select`). Entirely decoupled from `hearth/` — no code sharing, only the exported `.onnx` + config values cross the boundary.

## `models`

**Purpose:** Asset directory holding the trained wake-word model(s) consumed (eventually) by the runtime's wake detector.

**Key files:** `models/wake/calcifer.onnx` (963 KB binary ONNX classifier for "Calcifer", conv-attention architecture — not a text file, do not attempt to read it), `models/wake/models.json` (training manifest: per-model fpph/recall/threshold/gate_passed/trained_at, written by `training/manifest.py`).

**Look here for:** which wake-word model(s) exist and their eval metrics (`models.json`). Note: `hearth/` has no code yet that loads `calcifer.onnx` — the runtime consumer is roadmap (see architecture.md Open Questions).

## `packaging` (merged with `.github`)

**Purpose:** Builds hearth as a single-file PyInstaller binary per architecture, locally (`make release`) and in CI (tag-triggered GitHub Actions release).

**Key files:** `packaging/build.sh` (build driver: isolated `.build-venv`, PyInstaller invocation with `config.yaml` bundled and `--collect-submodules hearth`), `packaging/entry.py` (minimal PyInstaller entry point calling `hearth.app:main()`), `.github/workflows/release.yml` (matrix CI job: `ubuntu-24.04` x86_64 + `ubuntu-24.04-arm` aarch64, smoke test, `softprops/action-gh-release` upload on `v*` tags).

**Look here for:** how the distributable binary is produced, what native/system deps a build host needs (`portaudio19-dev`, `libportaudio2`, `libsndfile1`, `espeak-ng`), and the release-tag → GitHub-Release flow.
