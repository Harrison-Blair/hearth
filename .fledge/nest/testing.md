---
generated: 2026-07-17T06:36:02Z
commit: 2cf763f017cef0f330f2fb0df7157c947be1113a
agent: fledge-forager
fledge_version: 0.6.7
---

# Testing

Test framework, how to run tests, fixtures/doubles, and the per-module coverage map — `tests/` (21 files) plus `training/test_manifest.py`.

## Framework

pytest with `asyncio_mode = "auto"` (`pyproject.toml`) — async tests are bare `async def test_*()`, no `@pytest.mark.asyncio` decorator required. The suite is fully hermetic: all LLM and network calls are stubbed via `httpx.MockTransport` or `websockets` doubles; `tests/test_e2e_veneer.py` is the one exception that runs a real `websockets.serve()`/`connect()` pair on an ephemeral localhost port (still no real external services). No test touches a real Ollama/OpenRouter/Wikipedia endpoint — that verification is manual, via `MANUAL_SMOKE.md`.

```bash
pytest                        # all tests, from repo root
pytest path/to/test_x.py::test_name
pytest training/test_manifest.py   # separate, stdlib-only, doesn't need .venv-train
```
In a git worktree, use `python -m pytest` (not `.venv/bin/pytest`) or tests run against `main`'s code instead of the worktree's.

## Shared fixtures (`tests/conftest.py`)

- `_reset_logging_state()` — autouse; isolates root/`websockets` logger handlers between tests (FTHR-011).
- `llm_config()` — single "local" backend on `localhost:11434`, `qwen3:14b`; tool tier == default tier.
- `two_tier_llm_config()` — "local" (`http://local-llm.test/v1`) as default tier, "remote" (`https://remote-llm.test/v1`) as tool tier (FTHR-009 — the two-tier split under test).
- `canned_completion()` — factory returning an OpenAI-compatible completion JSON dict with configurable text/tool_calls/finish_reason/usage.
- Helpers: `make_local_backend_config(**overrides)` (LLMBackend builder), `make_mock_client(handler, base_url)` (wraps `httpx.MockTransport`), `HostRouter` (MockTransport handler that branches on `request.url.host`, tracks per-host call counts — used for tier-split tests where local vs. remote must be distinguishable).

## Test doubles

`_FakeLoop`, `_FakeRegistry`, `_FakeWebSocket`, `_Config`, `_Agent`, `_Persona`, `_Conversation` — minimal duck-typed doubles matching the real class's attribute/method interface, not full stubs. Purpose-built doubles for specific failure modes: `_RaisingTranscript` (RuntimeError, tests logging-failure non-fatality), `_RecordingConsult` (records session/turn/query context, tests concurrent-turn isolation), `_BlockingConsult` (sleeps forever, tests timeout handling), `_SlowFakeLoop` (delays return, tests client disconnect mid-turn in `test_e2e_veneer.py`).

## Coverage map (source module → test file(s))

| Source | Test file(s) |
|---|---|
| `hearth/app.py` | `test_app.py` |
| `hearth/config.py` | `test_config.py` (YAML/env/`.env` precedence, `resolve_config_path()`, API key resolution) |
| `hearth/brain/base.py`, `errors.py` | `test_brain_errors.py` (HTTP error, malformed body, bad tool args, API-key redaction, malformed tool-call structure) |
| `hearth/brain/local.py` | `test_local_backend.py` (completion parse, tool calls, retries, timeout non-retry, usage/reasoning-token capture, duration tracking) |
| `hearth/brain/remote.py` | `test_remote_backend.py` (Bearer auth, usage/model capture) |
| `hearth/brain/router.py` | `test_router.py` (tier selection, override, `brain_available()`) + `test_brain_guard.py` (guard-prompt injection, config-driven) |
| `hearth/loop.py` | `test_loop.py` (turn orchestration, history reconstruction, metrics, timeout) + `test_loop_tools.py` (`run_react_rounds()` ReAct logic, tool dispatch, nested metrics propagation) |
| `hearth/loop.py` + `hearth/tools/consult.py` | `test_orchestrator_persona.py`, `test_consult_brain.py` (nested ReAct, graceful degradation on `BrainError`/timeout, balanced tool-activity events, timeout logging) |
| `hearth/memory/log.py` | `test_event_log.py` (append/read session) |
| `hearth/memory/reader.py`, `consumer.py` | `test_layer2_reader.py` (cursor-based read, `NoOpConsumer`, write-path isolation) |
| `hearth/veneer/server.py`, `protocol.py` | `test_veneer.py` (roundtrip, tool-internals whitelist, error mapping, malformed-frame recovery) + `test_veneer_errors.py` (`curate_error()` policy, `ConnectionClosed` robustness, connection logging) |
| `hearth/veneer/client.py` | `test_veneer_client.py` |
| `hearth/logging_setup.py` | `test_console_formatter.py` (ANSI coloring, category dispatch, NO_COLOR/TTY) + `test_logging.py` (rotating handler, idempotency, websockets-logger routing) |
| `hearth/transcript.py` | `test_logging.py` (transcript ordering, non-fatal write failure) |
| `hearth/tools/wikipedia.py` | `test_wikipedia.py` (URL building, result/char limiting, User-Agent header) |
| `hearth/tools/consult.py`, `registry.py`, full stack | `test_e2e_veneer.py` (multiturn chat + consult over a real WebSocket, remote-tier split, remote-disabled fallback, disconnect mid-turn) |
| `training/manifest.py` (`remove` subcommand) | `training/test_manifest.py` |

## What's verified by the security-boundary tests specifically

- `tests/test_veneer.py::test_no_tool_internals_cross_boundary` — asserts forbidden keys (`query`, `arguments`, `observation`, `result`) never appear in any outbound wire message; this is the automated proof of the `serialize()` whitelist described in `architecture.md`.
- `tests/test_brain_errors.py::test_brain_error_never_leaks_api_key` — asserts the API key never appears in `BrainError.reason`, `.detail`, or `str()`.

## Manual verification

`MANUAL_SMOKE.md` — a three-phase procedure verifying the text spine against real Ollama, OpenRouter, and Wikipedia services; explicitly designed to distinguish environment issues (missing credentials, offline services) from actual spine bugs. Run this, not the automated suite, to confirm real-service integration.

## Test-verification discipline (repo-wide rule, per root `CLAUDE.md`)

A test only counts if it fails when the behavior breaks. New bug-fix tests must be run against the unfixed code (or with the fix reverted) to confirm they fail, then confirmed passing with the fix. Never trust a test that has only ever been seen passing.

## Open Questions

- Test coverage for `hearth/memory/consumer.py`'s `pull_once()` proof-of-concept beyond `test_layer2_reader.py`'s write-path isolation test was not fully enumerated by scouts — verify directly if extending Layer-2.
