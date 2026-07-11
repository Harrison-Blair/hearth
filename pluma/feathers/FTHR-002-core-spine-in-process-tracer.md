---
id: FTHR-002
title: Core spine in-process tracer
plumage: PLM-001
status: hatching
priority: P0
depends_on: [FTHR-001]
oversight: merge
authored: 2026-07-10T23:43:12Z
agent: fledge-orchestrate/planning
fledge_version: 0.3.0
---

# FTHR-002: Core spine in-process tracer

## Description
The thin end-to-end vertical slice, in-process (no WebSocket yet): a `Brain` interface with a working Local (Ollama, OpenAI-compatible) backend, a minimal router seam, a single-completion multi-turn ReAct loop, the persona no-op tail, and the event-log core. Proves the spine produces a logged, history-aware answer from a real backend, and defines the typed boundary interfaces that FTHR-003/004/005/006 widen. Backend calls are non-streaming; no tool rounds yet.

## Affected Modules
All new under `hearth/` (see `.fledge/nest/architecture.md` for the intended runtime shape, `.fledge/nest/data-model.md` for config sections consumed):
- `hearth/brain/base.py` — `Message`, `ToolSpec`, `ToolCall`, `BrainResult`, `Capabilities`, `Brain` protocol.
- `hearth/brain/local.py` — `LocalBackend` (OpenAI-compatible via httpx, non-streaming).
- `hearth/brain/router.py` — `Router` seam (`select(...) -> Selection`); local-only in this feather.
- `hearth/events.py` — `ToolActivity` intermediate event + `EventSink` type alias (the loop→veneer emit path).
- `hearth/tools/registry.py` — `ToolRegistry` seam (empty here).
- `hearth/memory/log.py` — `Event`, `EventLog` (SQLite append-only + `read_session`).
- `hearth/persona.py` — `restyle(...)` no-op.
- `hearth/loop.py` — `Loop.run_turn(...)`.
- `tests/` — `test_local_backend.py`, `test_event_log.py`, `test_loop.py`, `conftest.py`.

## Approach
- **Boundary types** (`brain/base.py`) — freeze these signatures; FTHR-004 (router) and FTHR-006 (tools) depend on them:
  - `Capabilities(supports_tools: bool, supports_streaming: bool, context_window: int, cost_tier: str)`
  - `Message(role: str, content: str | None, tool_calls: list[ToolCall] | None = None, tool_call_id: str | None = None)`
  - `ToolSpec(name: str, description: str, parameters: dict, label: str)` — `parameters` is a JSON-Schema dict; `label` is the veneer-safe coarse label.
  - `ToolCall(id: str, name: str, arguments: dict)`
  - `BrainResult(text: str | None, tool_calls: list[ToolCall], finish_reason: str, backend: str, tier: str)`
  - `Brain` protocol: attribute `capabilities: Capabilities`; `async def complete(self, messages: list[Message], tools: list[ToolSpec] | None) -> BrainResult`.
- **`LocalBackend`**: builds an OpenAI-compatible `/chat/completions` request from `config.llm.backends.local`, POSTs via an **injectable** `httpx.AsyncClient` (tests inject a `MockTransport`), parses `choices[0].message` into `BrainResult` (text + any `tool_calls`), non-streaming. `capabilities` read from the backend config.
- **`Router`**: constructed from `config.llm` (backends + tiers). `select(tools_available: bool = False, tier_override: str | None = None) -> Selection`, where `Selection(brain: Brain, tier: str, backend_name: str, reason: str)`. In this feather it returns the local backend with `tier="default"`, `reason="single-backend (FTHR-002)"`. FTHR-004 replaces the body with real tier logic **without changing this signature**.
- **`hearth/events.py`**: `ToolActivity(turn_id: str, phase: str, label: str)` (`phase` ∈ `{"start","end"}`) and `EventSink = Callable[[object], Awaitable[None]]`. A module-level `null_sink` no-op is the default. FTHR-006 emits `ToolActivity` through the sink; FTHR-003's veneer supplies a sink that serializes it to the wire. Defined here so the boundary type is frozen even though nothing emits it until FTHR-006.
- **`ToolRegistry`**: `specs() -> list[ToolSpec]` (empty here) and `async dispatch(name, args) -> str`. FTHR-006 populates it; the loop tolerates an empty registry.
- **`EventLog`**: SQLite table `events(id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, turn_id TEXT, ts_utc TEXT, type TEXT, provenance TEXT, payload_json TEXT)`. `append(session_id, turn_id, type, provenance, payload: dict) -> Event` inserts synchronously (UTC timestamp) and returns the row; `read_session(session_id, limit) -> list[Event]` returns events in `id` order. No update/delete method exists. `type` accepts the full enum (`user_input`, `routing_decision`, `tool_call`, `observation`, `final_answer`, `error`); this feather emits only `user_input` and `final_answer`.
- **`persona.restyle(text: str, ctx) -> str`**: async no-op returning `text` unchanged; called at the loop tail on the final answer only.
- **`Loop.run_turn(session_id, turn_id, transcript, emit: EventSink = null_sink) -> str`**: append `user_input`; reconstruct history via `read_session` bounded by `config.conversation.max_history_turns`; assemble `messages`; `sel = router.select(tools_available=False)`; append `routing_decision` (payload: `tier`, `backend_name`, `reason`); `result = await sel.brain.complete(messages, tools=None)`; `answer = await persona.restyle(result.text, ctx)`; append `final_answer`; return `answer`. The `emit` sink is unused here (FTHR-006 emits `ToolActivity` through it) and defaults to `null_sink` so this feather's tests call `run_turn` without it. No tool rounds (FTHR-006 adds them).

## Tests
Written test-first (write → observe FAIL for the expected reason → implement to green). Hermetic via `httpx.MockTransport`; shared fixtures in `tests/conftest.py`; `pytest`/`asyncio_mode=auto`, ruff line-length 100:
- `test_local_backend_parses_completion` — MockTransport returns a canned OpenAI-compatible body → `BrainResult.text` populated, `tool_calls` empty. (AC-2)
- `test_event_log_append_and_read` — appended events return in `id` order; `read_session` scopes by session; no mutation API is exposed. (AC-3)
- `test_loop_single_turn_logs_and_answers` — `run_turn` returns the backend text and appends `user_input`, `routing_decision`, `final_answer` in order. (AC-4)
- `test_loop_multi_turn_reconstructs_history` — a second `run_turn` on the same `session_id` includes the prior exchange (read from the log) in the messages passed to the backend; bounded by `max_history_turns`. (AC-5)
- `test_persona_restyle_noop` — `restyle` returns input unchanged; loop output equals backend text. (AC-6)

## Acceptance Criteria
- [ ] AC-1: The tests listed above were observed failing before implementation and pass after.
- [ ] AC-2: `LocalBackend` implements the `Brain` protocol and returns a parsed `BrainResult` from an OpenAI-compatible response (satisfies PLM-001 FC-3 partial, FC-7).
- [ ] AC-3: `EventLog` is append-only (no update/delete), stores the full event schema, and `read_session` returns session events in order (satisfies PLM-001 FC-12 partial).
- [ ] AC-4: `Loop.run_turn` produces an answer and appends `user_input`, `routing_decision`, `final_answer` for the turn, via a `Router.select` returning a `Selection`, with an `emit` sink seam wired for later `ToolActivity` (satisfies PLM-001 FC-12 partial).
- [ ] AC-5: Multi-turn history is reconstructed from the event log scoped to the session and bounded by `max_history_turns`, with no separate history store (satisfies PLM-001 FC-14).
- [ ] AC-6: The persona restyle stage runs at the loop tail as a no-op applied to final answers only (satisfies PLM-001 FC-11).
