---
generated: 2026-07-17T06:36:02Z
commit: 2cf763f017cef0f330f2fb0df7157c947be1113a
agent: fledge-forager
fledge_version: 0.6.7
---

# Modules

Repo map: every top-level module `fledge scan` reports, its purpose, key files, and where to look for what. Organized by module (the one concern doc that departs from topic-based organization).

## `root` (11 files)

**Purpose:** Project metadata, configuration schema/defaults, packaging entry points, and developer docs.

**Key files:** `pyproject.toml` (package metadata, 13 optional-dependency extras), `config.yaml` (active config), `default-config.yaml` (documented reference/defaults), `README.md` (quickstart + working-vs-roadmap table), `CLAUDE.md` (dev guidance), `MANUAL_SMOKE.md` (manual verification against live services), `Makefile` (`make release`/`make clean`), `.env.example` (secret template).

**Look here for:** which optional-dependency extra to install for a given capability; the difference between `config.yaml` and `default-config.yaml`; how secrets vs. tunables are split; release build commands.

## `hearth` (27 files) — the runtime package

Split across five concern areas for scouting; all live under `hearth/`.

### `hearth-core`: `app.py`, `config.py`, `loop.py`, `events.py`, `logging_setup.py`, `persona.py`, `transcript.py`, `__init__.py`

**Purpose:** Daemon entry point, object-graph wiring, the `Settings` config schema, the turn-processing engine (`Loop.run_turn`), the shared ReAct engine (`run_react_rounds`), logging, and per-session transcripts.

**Key files:** `app.py` (`main()`, `_run_daemon()` — wires the full object graph); `config.py` (`Settings`, 8 config sections, precedence cascade init→env→`.env`→YAML); `loop.py` (`Loop.run_turn()`, `run_react_rounds()` — shared by orchestrator and nested consult, `ReactRoundsMetrics`); `events.py` (`ToolActivity`, `EventSink` — the frozen Loop↔Veneer boundary type); `logging_setup.py` (`setup_logging()`, `ColorFormatter`, category-coded log lines); `persona.py` (`restyle()` — currently a no-op stub, placeholder for FTHR-011); `transcript.py` (`Transcript.append()` — best-effort, swallows `OSError`).

**Look here for:** how the daemon starts and wires every component; the full config schema; turn orchestration and ReAct round-capping; what crosses the Loop→Veneer boundary.

### `hearth-brain`: `brain/__init__.py`, `base.py`, `errors.py`, `local.py`, `openai_compat.py`, `remote.py`, `router.py`

**Purpose:** Pluggable, config-driven LLM backend abstraction. Frozen `Brain` protocol + two-tier routing (local/default, remote/tool).

**Key files:** `base.py` (frozen `Brain` protocol, `Message`, `ToolCall`, `ToolSpec`, `Capabilities`, `BrainResult`); `router.py` (`Router.select()`, `Router.brain_available()`, static `_BACKEND_CLASS_FOR_TIER` map); `openai_compat.py` (shared `_OpenAICompatBackend` — request/response handling, retry logic); `local.py`/`remote.py` (thin subclasses, tier defaults `"default"`/`"tool"`); `errors.py` (`BrainError(reason, detail)` — never leaks API keys).

**Look here for:** how a tier resolves to a backend; what a backend's public contract looks like; retry policy (only `httpx.TransportError` retried, not timeouts or HTTP errors); error normalization.

### `hearth-veneer`: `veneer/__init__.py`, `client.py`, `protocol.py`, `server.py`

**Purpose:** The localhost WebSocket control surface — today's only client-facing veneer. Candidate for rename to `chat` per upcoming plumage.

**Key files:** `server.py` (`Veneer` class — `serve()`, `_handle_connection()`, one turn at a time per connection, no ping keepalive); `protocol.py` (`serialize()` — the wire whitelist boundary; `curate_error()`; `Request` dataclass; `answer_message`/`done_message`/`error_message` builders); `client.py` (dev/test stdin/stdout client, `send_turn()` reused by integration tests).

**Look here for:** the wire protocol and its security whitelist; everywhere the current "veneer" naming would need to change for a rename to `chat` (see list below); WebSocket connection/session lifecycle.

**Rename-to-`chat` reference list** (from `hearth-veneer.md`, verify line numbers before editing):
- `Veneer` class (`server.py`)
- `VeneerConfig` class and `Settings.veneer` field (`hearth/config.py`)
- `HEARTH_VENEER__HOST` / `HEARTH_VENEER__PORT` env vars
- `hearth/veneer/` package path
- imports in `hearth/app.py` (`from hearth.veneer.server import Veneer`) and in `tests/test_veneer*.py`
- the `"veneer"` string literal logged as an EventLog provenance tag in `server.py`
- docstring/comment references ("veneer contract", "veneer wire protocol") in `server.py` and `client.py`

### `hearth-memory-tools` (merged small modules): `memory/__init__.py`, `consumer.py`, `log.py`, `reader.py`, `tools/__init__.py`, `consult.py`, `registry.py`, `wikipedia.py`

**Purpose:** Two integrated subpackages — `memory/` (append-only sqlite event log + read-only cursor pull interface) and `tools/` (tool registry + the nested `consult_brain` ReAct tool + Wikipedia).

**Key files:** `memory/log.py` (`EventLog` — schema `events(id, session_id, turn_id, ts_utc, type, provenance, payload_json)`; `append()`, `read_session()`; no update/delete exposed); `memory/reader.py` (`EventReader` — `read_since(cursor, limit)`, `latest_cursor()`; the Layer-2 seam); `memory/consumer.py` (`Layer2Consumer` protocol, `NoOpConsumer` — proof-of-concept only, no scheduler wired); `tools/consult.py` (`BrainConsult.__call__()` — the orchestrator's one exposed tool, runs nested `run_react_rounds()` on the tool tier, degrades to text observation on `BrainError`/timeout); `tools/registry.py` (`ToolRegistry.specs()`/`dispatch()` — Wikipedia conditionally registered); `tools/wikipedia.py` (`wikipedia_search()` — Wikimedia REST API, config-driven result/char limits).

**Look here for:** the event log schema and its append-only guarantee; the cursor-based Layer-2 read seam; how `consult_brain` is implemented and how tools are dispatched by name.

## `tests` (21 files)

**Purpose:** Hermetic test suite for the entire runtime spine — all LLM/network calls stubbed (`httpx.MockTransport`, `websockets` doubles); no real backends invoked.

**Key files:** `conftest.py` (shared fixtures: `llm_config`, `two_tier_llm_config`, `canned_completion`, autouse `_reset_logging_state`, `make_mock_client`, `HostRouter`); coverage spans backend layer (`test_brain_errors.py`, `test_local_backend.py`, `test_remote_backend.py`, `test_router.py`, `test_brain_guard.py`), orchestrator (`test_loop.py`, `test_loop_tools.py`, `test_orchestrator_persona.py`, `test_consult_brain.py`), veneer (`test_veneer.py`, `test_veneer_errors.py`, `test_veneer_client.py`, `test_e2e_veneer.py`), memory (`test_event_log.py`, `test_layer2_reader.py`), config (`test_config.py`), logging (`test_console_formatter.py`, `test_logging.py`), app (`test_app.py`), Wikipedia (`test_wikipedia.py`).

**Look here for:** how to write a hermetic test against any given source module; the full per-module test coverage map (see `testing.md`).

## `training` (9 files)

**Purpose:** Wake-word training pipeline for `livekit-wakeword`, entirely isolated from the runtime (separate `.venv-train`, never shares the runtime venv). Fully synthetic (no recordings). Produces `.onnx` models the runtime does not yet consume.

**Key files:** `bootstrap.sh` (one-time `.venv-train` setup, ROCm PyTorch); `train.py` (single-model pipeline: generate→augment→train→export→eval); `train_batch.py` (sequential multi-phrase batch trainer, reads `phrases.txt`); `manifest.py` (stdlib-only model registry — `models/wake/models.json`; subcommands `upsert`/`list`/`regen`/`remove`/`select`); `vesta.yaml`/`prometheus.yaml` (per-phrase production training configs); `phrases.txt` (active wake phrases: Vesta, Prometheus, Ignis); `test_manifest.py` (pytest, stdlib-only, no `.venv-train` needed).

**Look here for:** how a wake-word model is trained and exported; how `manifest.py select` points `config.yaml` at a trained model and sets `wake.threshold`; the fully-synthetic data generation approach (Piper VITS + ACAV100M + MIT RIRs + MUSAN).

## `misc` (merged small modules): `models`, `packaging`, `.github`

**Purpose:** Build, packaging, and CI/CD — single-file binary construction (PyInstaller), architecture-native builds, GitHub Actions release automation, and the current wake-word model artifact.

**Key files:** `packaging/build.sh` (PyInstaller `--onefile` build, respects `HEARTH_BUILD_EXTRAS`, bundles `config.yaml`); `packaging/entry.py` (PyInstaller analysis entry point, calls `hearth.app:main`); `.github/workflows/release.yml` (triggers on `v*` tags/manual dispatch; builds x86_64 + aarch64 natively, no cross-compile; smoke-tests each binary; attaches to GitHub Release); `models/wake/vesta.onnx` (960,600-byte ONNX artifact, not yet consumed by runtime).

**Look here for:** how release binaries are built and published; what system packages the frozen binary needs (portaudio, libsndfile, espeak-ng); the current wake-word model artifact's status (trained, not wired in).

## Open Questions

- How does `training/` eventually integrate with the runtime to load and use `.onnx` models?
- What additional CLI commands does `hearth` support beyond `hearth run`?
