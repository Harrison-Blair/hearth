---
id: FTHR-012
title: Veneer error-surfacing and WebSocket robustness
plumage: PLM-002
status: fledged
priority: P1
depends_on: [FTHR-008, FTHR-009]
authored: 2026-07-11T02:54:10Z
agent: fledge-orchestrate/planning
fledge_version: 0.3.4
---

# FTHR-012: Veneer error-surfacing and WebSocket robustness

## Description
`Veneer._handle_connection` (`hearth/veneer/server.py`) currently catches any exception from `Loop.run_turn` with a bare `except Exception`, logs the real message to the `EventLog`, but always sends the client the generic `"the turn failed"` — even for a `BrainError` (FTHR-008) whose `.reason` is specifically curated to be client-safe. Separately, nothing catches `websockets.ConnectionClosed`, so a client disconnecting mid-turn raises out of `_handle_connection` and (per the current `async with websockets.serve(...)` usage) can take down the connection handling for that client ungracefully rather than being logged and the server continuing to serve other connections. This feather curates `BrainError` reasons to the client and hardens the connection loop against a disconnect.

## Affected Modules
- `hearth/veneer/server.py:34,44-51` (`Veneer._handle_connection`) — in the `except` block: branch on `isinstance(exc, BrainError)` — if so, send `error_message(request.turn_id, exc.reason)` (the curated, client-safe reason from FTHR-008); otherwise keep the existing generic `"the turn failed"`. In both cases the real detail (`exc` for non-`BrainError`, `exc.detail` for `BrainError`) still goes to the `EventLog` via the existing `self._log.append(..., "error", "loop", {"message": ...})` call — never send `.detail` to the client. Wrap the per-message loop (`async for raw in websocket:`) so a `websockets.ConnectionClosed` raised while awaiting `run_turn` or sending a reply is caught, logged (via the FTHR-011 logging setup, at INFO/WARNING — a disconnect isn't an error), and the handler returns cleanly instead of propagating out of `websockets.serve`'s connection handler.
- `hearth/veneer/protocol.py` — add a small `curate_error(exc: Exception) -> str` helper (`BrainError` → `exc.reason`; anything else → the generic `"the turn failed"`) so the curation policy is testable independently of the server's try/except plumbing. `serialize()` itself is untouched — this is a server call-site + policy change, not a wire-format or whitelist change.
- New `tests/test_veneer_errors.py`.
- `tests/test_e2e_veneer.py` — touch to cover a `BrainError`-raising turn's client-visible error message, and a `ConnectionClosed` disconnect not crashing the server (reworked/extended, not a full rewrite — the base consult-flow event/wire sequences were already reworked by FTHR-009).

## Approach
- Client is unchanged (per the plan) — `hearth/veneer/client.py` already calls `_print_message` on any `type: "error"` payload and just prints `message`, so no client-side work is needed; this feather is purely server-side policy + robustness.
- `curate_error` keeps the "what reaches the client" decision in one small, directly-testable function rather than scattering `isinstance` checks — `_handle_connection`'s except block becomes `await websocket.send(json.dumps(error_message(request.turn_id, curate_error(exc))))`.
- The privacy whitelist stays closed: `curate_error` only ever returns `BrainError.reason` (already curated by FTHR-008 to be client-safe) or the fixed generic string — never `str(exc)`, never `.detail`.
- `ConnectionClosed` handling wraps the same per-connection `async for` loop `_handle_connection` already has — catch `websockets.ConnectionClosed` around the body of the loop (or around the whole method), log-and-return rather than re-raise, so `websockets.serve`'s dispatcher doesn't see an unhandled exception from one connection and the outer `serve()` call keeps accepting new connections regardless.

## Tests
Written test-first in `tests/test_veneer_errors.py` (new), using an in-memory fake `Loop`/websocket double (matching the existing `test_veneer.py`/`test_e2e_veneer.py` patterns rather than a real socket):
- `test_curate_error_brain_error_returns_reason` — `curate_error(BrainError("backend unreachable", detail="..."))` returns `"backend unreachable"`.
- `test_curate_error_generic_exception_returns_generic_message` — `curate_error(ValueError("boom"))` returns the fixed `"the turn failed"` string, not `str(exc)`.
- `test_brain_error_reaches_client_as_curated_reason` — drive `_handle_connection` with a fake `Loop.run_turn` that raises `BrainError`; assert the client receives an `error` message whose `message` equals the curated reason (not the generic string), and the `EventLog`'s `error` event payload still records the real detail.
- `test_generic_exception_reaches_client_as_generic_message` — same shape with a plain `Exception`; client message stays `"the turn failed"`; `EventLog` still records `str(exc)`.
- `test_connection_closed_mid_turn_handled_cleanly` — a fake websocket that raises `websockets.ConnectionClosed` while `run_turn` is in flight (or while sending); assert `_handle_connection` returns without propagating, and (via `caplog`) a clean log record is produced rather than an unhandled-exception traceback.
- `test_serve_continues_after_one_connection_disconnects` (in `test_e2e_veneer.py`, extended) — an end-to-end-flavored check that a second connection after a first `ConnectionClosed` still completes a normal turn against the running server.

Implementation order: write the above against the unchanged code (curate_error doesn't exist, `_handle_connection` always sends the generic message and doesn't catch `ConnectionClosed`), capture the failures, then implement until green.

## Acceptance Criteria
- [x] AC-1: The tests listed above were observed failing before implementation and pass after.
- [x] AC-2: A `BrainError` out of `run_turn` reaches the client's `error.message` as the curated `reason`, not `"the turn failed"`. Satisfies PLM-002 FC-9.
- [x] AC-3: A non-`BrainError` exception still reaches the client as the generic `"the turn failed"`; the real detail is still written to the `EventLog`. Satisfies PLM-002 FC-9.
- [x] AC-4: `serialize()` is unchanged; no tool content crosses the wire boundary (existing `forbidden_keys`/content-free assertions from `test_e2e_veneer.py` still hold).
- [x] AC-5: A client disconnect mid-turn (`websockets.ConnectionClosed`) is handled cleanly — logged, not raised — and the server keeps serving other connections afterward. Satisfies PLM-002 FC-10.
