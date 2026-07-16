---
generated: 2026-07-15T23:27:05Z
commit: e41ba8a73a56364e7c3bb1acf1332cadab817e45
agent: fledge-forager
fledge_version: 0.5.5
---

# Testing

Frameworks, how to run tests, fixture/mocking conventions, and the file→feather coverage map for `tests/`.

## Framework and run commands

- **pytest** with **pytest-asyncio**, `asyncio_mode=auto` (confirmed in `pyproject.toml`) — `async def test_*()` needs no `@pytest.mark.asyncio` decorator.
- `pytest` — run everything.
- `pytest tests/test_loop.py` — one file.
- `pytest tests/test_loop.py::test_loop_single_turn_logs_and_answers` — one test.
- `pytest -v` — verbose.
- `ruff check .` — lint, line-length 100.
- Non-hermetic manual smoke procedure lives in `MANUAL_SMOKE.md` (real Ollama/OpenRouter/Wikipedia) — separate from the hermetic pytest suite.

## Shared fixtures (`tests/conftest.py`)

- `_reset_logging_state` (autouse) — isolates process-global logging handlers between tests.
- `llm_config` / `two_tier_llm_config` — `LLMBackend`/`LLMConfig` builders.
- `canned_completion` — OpenAI-shaped response builder (`_tool_call_completion(name, args, call_id)`, `_chat_completion(text)`).
- `HostRouter` — multi-backend request multiplexer keyed on `request.url.host`, tracks per-host call counts for deterministic assertions.
- `make_mock_client` — wraps `httpx.AsyncClient` with a `MockTransport` handler.

## Mocking conventions

- **`httpx.MockTransport`** — per-test `handler(request) -> httpx.Response`; used for every LLM and Wikipedia call so tests never hit real services.
- **Fake/duck-typed config objects** — test-local `_Config`, `_Conversation`, `_Agent`, `_Persona` classes carrying only the attributes a test needs, avoiding a full `Settings` load.
- **Fake doubles** — `FakeLoop` (scripted answer/activities/`raise_exc`), `FakeRegistry` (specs + dispatch), `FakeWebSocket` (`aiter`, `send` with optional `close_on_send`) for veneer unit tests.
- **Timeout/failure simulation** — `asyncio.sleep()` in a mock handler to trigger `ReadTimeout`; short `timeout=0.05s` configs to expire fast; `httpx.ConnectError`/`httpx.ReadTimeout` raised directly in handlers.
- **Concurrency isolation** — `asyncio.gather()` tests verify concurrent `run_turn` calls keep separate `session_id`/`turn_id`/emit-sink/event-log entries.
- **Per-test isolation** — `EventLog` built in `tmp_path`; logging state reset via the autouse fixture.

## Coverage map (file → feather → what it covers)

| Test file | Feather | Covers |
|---|---|---|
| `test_config.py` | FTHR-003 | `Settings` precedence: YAML → `HEARTH_*` env → `.env` → `HEARTH_CONFIG` override; tier resolution |
| `test_app.py` | — | CLI entry, LLM client timeout wiring, tool registry injection into `Loop` |
| `test_brain_errors.py`, `test_local_backend.py` | FTHR-004, FTHR-008 | `LocalBackend` OpenAI-compat parsing, transient retries, timeout non-retry, connection errors, `BrainError` crash-hardening, API-key sanitization |
| `test_remote_backend.py` | FTHR-005 | `RemoteBackend` Bearer auth header, completion parsing |
| `test_router.py` | FTHR-006 | `Router.select()` deterministic tier routing, `tier_override`, `brain_available()` gating |
| `test_brain_guard.py` | FTHR-010 | Nested `BrainConsult` carries `persona.brain_guard_prompt` as `messages[0]` system message |
| `test_loop.py` | FTHR-007 | `Loop.run_turn()` single/multi-turn, history reconstruction (`max_history_turns`), persona system prompt, restyle no-op |
| `test_loop_tools.py`, `test_consult_brain.py` | FTHR-009 | Orchestrator offers only `consult_brain`; nested Wikipedia call on remote tier; per-turn tool-activity emission; round cap; timeout with balanced emit; concurrent turn isolation |
| `test_orchestrator_persona.py` | — | Calcifer system prompt present on every orchestrator turn; identity queries stay local-only (no remote-tier leak) |
| `test_event_log.py` | — | `EventLog` append-only (no update/delete API), session-scoped reads, id ordering |
| `test_layer2_reader.py` | — | `EventReader` cursor interface (`latest_cursor`, `read_since`), `NoOpConsumer`, write path unaffected by reader |
| `test_logging.py` | FTHR-011 | Rotating handler setup/idempotency, console toggle, `websockets` logger routed separately (`propagate=False`), dual-model logging, per-session transcript ordering, transcript/logging failures don't crash a turn |
| `test_veneer.py`, `test_veneer_client.py`, `test_veneer_errors.py` | FTHR-001 | WebSocket roundtrip via `send_turn()`; message types (`answer`/`tool_activity`/`done`/`error`); protocol whitelist enforcement (no `query`/`arguments`/`observation`/`result` leak); malformed frame → error + recover; `curate_error()` mapping; stdin-offload keepalive behavior |
| `test_wikipedia.py` | FTHR-009 | `wikipedia_search()` REST JSON parsing, absolute-URL fallback, `result_count`/`max_chars` limits, `User-Agent` header |
| `test_e2e_veneer.py` | — | Full stack assembled for real (`Veneer`/`Loop`/`Router`/`BrainConsult`/`ToolRegistry`/`EventLog`), all external calls via `MockTransport`; two-tier routing verified by host; remote-disabled stays local-only; client disconnect mid-turn handled cleanly |

Roughly 70+ test functions across 19 files. No test suite exists for `training/` (informal — see `domain.md` Open Questions) or for the `root`-level packaging scripts beyond CI's build smoke test (`<binary> --version`, cold start with debug logging).

## Open Questions

- None beyond the training-pipeline's lack of an automated test suite, tracked in `domain.md`.
