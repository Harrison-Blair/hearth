---
id: FTHR-003
title: Veneer WebSocket contract client and daemon
plumage: PLM-001
status: egg
priority: P0
depends_on: [FTHR-002]
oversight: merge
authored: 2026-07-11T00:15:30Z
agent: fledge-orchestrate/planning
fledge_version: 0.3.0
---

# FTHR-003: Veneer WebSocket contract client and daemon

## Description
Expose the in-process spine (FTHR-002) over the localhost WebSocket veneer contract and make `hearth run` a working daemon. Adds the wire protocol, a WebSocket server that drives `Loop.run_turn` per inbound turn, a trivial text client (reused by the integration test), and the content-free `ToolActivity` forwarding path. Completes the end-to-end tracer over the wire. The veneer is a generic forwarder of a typed event union — it never sees tool-call reasoning.

## Affected Modules
- `hearth/veneer/protocol.py` — wire messages + `serialize`.
- `hearth/veneer/server.py` — `Veneer` WebSocket server.
- `hearth/veneer/client.py` — trivial stdin/stdout text client.
- `hearth/app.py` — `run` subcommand wires the spine and serves (extends FTHR-001's stub).
- `pyproject.toml` — new `veneer = ["websockets"]` extra, added to `all` (see `.fledge/nest/dependencies.md` for the extras pattern).
- `tests/test_veneer.py`.

## Approach
- **New dependency:** `websockets` (asyncio WebSocket server/client). Add as a `veneer` extra and include it in `all`, per the per-phase extras convention (`.fledge/nest/conventions.md`).
- **`protocol.py`**: inbound `Request(turn_id: str, final_user_transcript: str)` parsed from JSON. Outbound wire messages, each a JSON object tagged with `turn_id` and a `type`: `tool_activity{phase, label}`, `answer{text}`, `done`, `error{message}`. `serialize(core_event) -> dict` maps `events.ToolActivity` → a `tool_activity` message using **only** `phase` and `label` — a whitelist that structurally cannot carry query, arguments, observation, or result content. Unknown event types raise (fail loud, never leak).
- **`server.py`**: `Veneer(loop, log, config)`. On connect, assign a `session_id` (per connection). For each inbound `Request`: build an `emit` sink that calls `serialize` and writes the resulting message to the socket; `answer_text = await loop.run_turn(session_id, turn_id, transcript, emit=sink)`; send `answer{answer_text}` then `done`. On any exception from the turn: append an `error` event to the log (`type="error"`, provenance = the failing stage) and send `error{message}` (message is a safe summary, not internals). One turn at a time per connection.
- **`client.py`**: connects to `config.veneer.host/port`, reads lines from stdin, sends each as a `Request` with a generated `turn_id`, and prints inbound messages (a `tool_activity` prints e.g. `…searching`, `answer` prints the text). Small and dependency-light; used by the integration test and the manual smoke check.
- **`app.py run`**: construct `EventLog`, `Router`, `ToolRegistry`, `Persona`, `Loop` from config, then `Veneer(...).serve(host, port)`. Replaces FTHR-001's "lands in FTHR-003" stub.

## Tests
Written test-first (write → observe FAIL → implement to green). `tests/test_veneer.py`, driving an in-process `Veneer` (loopback) with a fake `Loop`/backend where useful; `pytest`/`asyncio_mode=auto`:
- `test_veneer_roundtrip` — client sends a `Request`; receives `answer` then `done` tagged with the same `turn_id`; the turn's `user_input`/`final_answer` events are in the log. (AC-2, AC-3)
- `test_no_tool_internals_cross_boundary` — for a turn that emits a `ToolActivity`, every outbound message is a whitelisted type and no message contains query/arguments/observation/result fields. (AC-4)
- `test_loop_error_maps_to_error_message` — a `Loop.run_turn` that raises produces a wire `error{message}` (no internals) and appends an `error` event to the log. (AC-5)

## Acceptance Criteria
- [ ] AC-1: The tests listed above were observed failing before implementation and pass after.
- [ ] AC-2: The localhost WebSocket contract accepts `{turn_id, final_user_transcript}` and emits, tagged with that `turn_id`, zero+ `tool_activity` signals, one `answer`, and a terminal `done`/`error` (satisfies PLM-001 FC-10).
- [ ] AC-3: `hearth run` starts a working daemon serving the contract; the trivial text client completes a turn against it (satisfies PLM-001 FC-1; contributes to AC-7).
- [ ] AC-4: No tool query, arguments, or observation content ever crosses the veneer boundary; `ToolActivity` carries only `phase` + coarse `label` (satisfies PLM-001 FC-10, contributes to PLM AC-6).
- [ ] AC-5: A turn-level failure yields a wire `error` message with no internals and an `error` event appended to the log (contributes to PLM-001 FC-12).
