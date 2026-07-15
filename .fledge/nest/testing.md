---
generated: 2026-07-15T22:30:28Z
commit: a8489b1afa55662a54ba66548a2e176584a3f387
agent: fledge-forager
fledge_version: 0.5.4
---

# Testing

Frameworks, how to run tests, and what's actually covered, for both the automated suite and the manual live-service procedure.

## Framework & configuration

- **pytest** with `asyncio_mode=auto` — async test functions need no `@pytest.mark.asyncio` decorator (root.md, tests.md, `CLAUDE.md`).
- **pytest-asyncio** and **ruff** installed via the `dev` extra (`pip install -e '.[dev]'`).
- Run: `pytest` (whole suite), `pytest path/to/test_x.py::test_name` (one test), `ruff check .` (lint, line-length 100).
- 19 test files under `tests/`, 60+ test functions (tests.md).

## Hermeticity

- All I/O is mocked — no live network/services required for the automated suite:
  - **httpx**: `AsyncClient` + `MockTransport`, asserting on captured `Request`/`Response` objects, simulating `ConnectError`/`ReadTimeout`/`UnsupportedProtocol`.
  - **websockets**: real `websockets.serve` + `websockets.connect` against a loopback server in `test_e2e_veneer.py`, but no external service.
  - `HostRouter` (in `conftest.py`) branches mocked responses by `request.url.host`, letting a single mock transport stand in for both the local and remote LLM backend simultaneously, with per-host call counters for routing assertions (tests.md).
- `_reset_logging_state` — autouse fixture that clears root/websockets logger handlers between tests, addressing global-handler leakage from `hearth.logging_setup.setup_logging()` (tests.md).

## Coverage by area (from `tests/` file names + report content)

| Area | File(s) | What's asserted |
|---|---|---|
| Config | `test_config.py` | YAML → env → secret precedence, `HEARTH_CONFIG` resolution, missing-file errors |
| Backends | `test_local_backend.py`, `test_remote_backend.py` | Response parsing, tool-call extraction, retry logic (only `ConnectError` confirmed retried), timeout handling, Bearer-token auth |
| Errors | `test_brain_errors.py` | HTTP status curation, malformed-body handling, bad tool arguments, API-key redaction from `BrainError.detail` |
| Routing | `test_router.py` | `Router.select()` tier resolution (default always local, remote via `tier_override`), `brain_available()` gating |
| Orchestration | `test_loop.py`, `test_loop_tools.py` | History reconstruction bounded by `max_history_turns`, persona system-prompt injection, orchestrator tier offering only `consult_brain`, nested wikipedia routing, concurrent-turn isolation |
| Nested consult | `test_consult_brain.py`, `test_brain_guard.py` | ReAct over wikipedia with error degradation/timeout handling, brain-guard system prompt on nested calls |
| Persona | `test_orchestrator_persona.py` | Persona prompt injected as `messages[0]`; identity questions stay local-only (structural guarantee) |
| Veneer/WebSocket | `test_veneer.py`, `test_veneer_errors.py`, `test_e2e_veneer.py` | Roundtrip, **tool-activity opacity boundary** (no query/arguments/result crosses the wire), error mapping (`BrainError.reason` vs. generic "the turn failed"), connection-closed recovery, full-stack integration |
| Event log | `test_event_log.py` | Append-only contract (no update/delete API), session-scoped reads |
| Memory reader | `test_layer2_reader.py` | `EventReader` cursor protocol, `pull_once()` consumer pattern |
| Logging | `test_logging.py` | `RotatingFileHandler` setup/idempotency, dual-model (local+remote) logging, transcript file ordering |
| App wiring | `test_app.py` | `main`, `_build_llm_clients`, `_run_daemon` |
| Wikipedia tool | `test_wikipedia.py` | Query parsing, URL building with/without `base_url`, `result_count`/`max_chars` bounds |

(tests.md)

## What's not covered by the automated suite

- **`packaging/`, `.github/workflows/release.yml`** — no unit tests; validated only by the CI smoke test (`--version`, DEBUG startup) which proves the frozen binary's imports resolve, not full behavior (packaging.md).
- **`training/`** — no unit tests observed for `train.py`, `train_batch.py`, or `manifest.py`; the pipeline's own `--smoke` mode (200 samples / 500 steps) is a fast plumbing check, not a pytest-discoverable test (training.md).
- **`models/`** — asset directory, not testable code.
- **Root config files** — `config.yaml`/`default-config.yaml` are exercised indirectly through `test_config.py` against `hearth/config.py`, not tested standalone.

## Manual testing

- `MANUAL_SMOKE.md` — a manual procedure run against **real** Ollama, OpenRouter, and Wikipedia services (not automated): start `hearth run`, drive it with `python -m hearth.veneer.client`, and check documented environment-issue triage steps (root.md).

## Open Questions

- Is there CI enforcement of `pytest`/`ruff` on PRs, or are they run only locally? Not visible in the assigned root/`.github` files beyond the release workflow (root.md, packaging.md).
- `max_retries` / retry policy: tests confirm `ConnectError` is retried but not `ReadTimeout` — is the retry-eligible exception set intentionally narrow, or incomplete? (tests.md)
