# FTHR-012 molt evidence

## AC-1

Tests written first in `tests/test_veneer_errors.py` (new) and
`tests/test_e2e_veneer.py` (extended with
`test_serve_continues_after_one_connection_disconnects`), run against the
unchanged pre-implementation code.

Command:
```
cd /home/penguin/.claude/jobs/f05ea59d/tmp/burrows/FTHR-012
.venv/bin/python -m pytest tests/test_veneer_errors.py tests/test_e2e_veneer.py::test_serve_continues_after_one_connection_disconnects -v
```

Captured output (pre-implementation):
```
============================= test session starts ==============================
platform linux -- Python 3.14.6, pytest-9.1.1, pluggy-1.6.0 -- /home/penguin/source/hearth/.venv/bin/python
cachedir: .pytest_cache
rootdir: /home/penguin/.claude/jobs/f05ea59d/tmp/burrows/FTHR-012
configfile: pyproject.toml
plugins: asyncio-1.4.0, anyio-4.14.1
asyncio: mode=Mode.AUTO, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collecting ... collected 1 item / 1 error

==================================== ERRORS ====================================
_________________ ERROR collecting tests/test_veneer_errors.py _________________
ImportError while importing test module '/home/penguin/.claude/jobs/f05ea59d/tmp/burrows/FTHR-012/tests/test_veneer_errors.py'.
Hint: make sure your test modules/packages have valid Python names.
Traceback:
/usr/lib/python3.14/importlib/__init__.py:88: in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
tests/test_veneer_errors.py:17: in <module>
    from hearth.veneer.protocol import curate_error
E   ImportError: cannot import name 'curate_error' from 'hearth.veneer.protocol' (/home/penguin/.claude/jobs/f05ea59d/tmp/burrows/FTHR-012/hearth/veneer/protocol.py)
=========================== short test summary info ============================
ERROR tests/test_veneer_errors.py
!!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
=============================== 1 error in 0.07s ===============================
```

This is the expected failure: `curate_error` does not exist yet in
`hearth/veneer/protocol.py`, so the whole new test module fails to even
collect — the pre-implementation code has no curation policy at all
(`_handle_connection` always sends the generic `"the turn failed"` message
and has no `ConnectionClosed` handling).

Isolated confirmation that each test in the new module fails for the
expected reason (not just import-error masking): temporarily replaced the
`from hearth.veneer.protocol import curate_error` line with a local stub
that always returns `"the turn failed"` (i.e. today's actual behavior) so
the module could collect, then ran the suite against the unchanged
`hearth/veneer/server.py`/`protocol.py`:

```
$ .venv/bin/python -m pytest tests/test_veneer_errors.py -v
...
FAILED tests/test_veneer_errors.py::test_curate_error_brain_error_returns_reason - AssertionError: assert 'the turn failed' == 'backend unreachable'
FAILED tests/test_veneer_errors.py::test_brain_error_reaches_client_as_curated_reason - AssertionError: assert 'the turn failed' == 'backend unreachable'
FAILED tests/test_veneer_errors.py::test_connection_closed_mid_turn_handled_cleanly - websockets.exceptions.ConnectionClosed: no close frame received or sent
3 failed, 2 passed in 0.04s
```

- `test_curate_error_brain_error_returns_reason` / `test_brain_error_reaches_client_as_curated_reason`
  fail because there is no curation policy yet — everything maps to the
  generic message.
- `test_connection_closed_mid_turn_handled_cleanly` fails with an
  **uncaught** `websockets.exceptions.ConnectionClosed` raised out of
  `Veneer._handle_connection` (traceback: `server.py:53`,
  `await websocket.send(json.dumps(answer_message(...)))`), because the
  current code's `except Exception` block only wraps the `run_turn` call —
  the reply `websocket.send(...)` calls (both the error-path one and the
  two success-path ones after the try/except) are unwrapped, so a
  `ConnectionClosed` raised from `send()` propagates uncaught. This is
  exactly the pre-fix behavior the spec describes.
- `test_curate_error_generic_exception_returns_generic_message` and
  `test_generic_exception_reaches_client_as_generic_message` pass under the
  stub (the generic-message path is already today's actual behavior) — they
  pin the "stays generic" side of the contract and are expected to keep
  passing after the real implementation lands.
- The stub was discarded (not committed); the module reverts to importing
  the real `curate_error`, which does not yet exist, so the file fails to
  collect (`ImportError`) against the true unchanged code, as shown above.

The one extended e2e test (`test_serve_continues_after_one_connection_disconnects`)
passes even pre-implementation, because `websockets.serve` already isolates
each connection in its own asyncio task — an unhandled exception in one
connection's handler doesn't crash `serve()`'s ability to accept other
connections regardless of this feather's fix. That structural fact is why
the spec's real pinning coverage for AC-5 is the unit-level
`test_connection_closed_mid_turn_handled_cleanly` (asserts no propagation
and a clean, non-ERROR log record) rather than the e2e test alone; the e2e
test is kept as the "reworked/extended" integration-flavored check the spec
calls for and remains green as a regression guard throughout.

Post-implementation run (after `curate_error` + the `_handle_connection`
rework):
```
$ .venv/bin/python -m pytest tests/test_veneer_errors.py tests/test_e2e_veneer.py::test_serve_continues_after_one_connection_disconnects -v
============================= test session starts ==============================
platform linux -- Python 3.14.6, pytest-9.1.1, pluggy-1.6.0
collected 6 items

tests/test_veneer_errors.py::test_curate_error_brain_error_returns_reason PASSED [ 16%]
tests/test_veneer_errors.py::test_curate_error_generic_exception_returns_generic_message PASSED [ 33%]
tests/test_veneer_errors.py::test_brain_error_reaches_client_as_curated_reason PASSED [ 50%]
tests/test_veneer_errors.py::test_generic_exception_reaches_client_as_generic_message PASSED [ 66%]
tests/test_veneer_errors.py::test_connection_closed_mid_turn_handled_cleanly PASSED [ 83%]
tests/test_e2e_veneer.py::test_serve_continues_after_one_connection_disconnects PASSED [100%]

6 passed in 0.43s
```

## AC-2

`curate_error(BrainError(...))` returns `.reason`, and
`test_brain_error_reaches_client_as_curated_reason` drives a real
`_handle_connection` call with a fake `Loop.run_turn` that raises
`BrainError("backend unreachable", detail="leaked internal detail")`,
asserting the client's `error.message` equals `"backend unreachable"` (not
`"the turn failed"`).

Implementation: `hearth/veneer/protocol.py` adds `curate_error`; the
`except` block in `hearth/veneer/server.py::_handle_connection` now sends
`error_message(request.turn_id, curate_error(exc))` instead of the
hardcoded generic string.

Command:
```
.venv/bin/python -m pytest tests/test_veneer_errors.py::test_curate_error_brain_error_returns_reason tests/test_veneer_errors.py::test_brain_error_reaches_client_as_curated_reason -v
```
Output:
```
tests/test_veneer_errors.py::test_curate_error_brain_error_returns_reason PASSED
tests/test_veneer_errors.py::test_brain_error_reaches_client_as_curated_reason PASSED
2 passed in 0.03s
```

## AC-3

`test_curate_error_generic_exception_returns_generic_message` pins
`curate_error(ValueError("boom"))` to the fixed string, never `str(exc)`.
`test_generic_exception_reaches_client_as_generic_message` drives
`_handle_connection` with a plain `RuntimeError("boom: leaked internal
detail")`; asserts the client's `error.message` is exactly
`"the turn failed"` and that the `EventLog`'s `error` row's
`payload_json` still contains `"boom: leaked internal detail"` (the real
detail keeps going to the log, only the client-facing message is curated).

Implementation: in `_handle_connection`, the logged detail is now
`exc.detail if isinstance(exc, BrainError) else str(exc)` — for a
non-`BrainError` this is unchanged (`str(exc)`); the client always gets
`curate_error(exc)`, which for a non-`BrainError` is the fixed generic
string.

Command:
```
.venv/bin/python -m pytest tests/test_veneer_errors.py::test_curate_error_generic_exception_returns_generic_message tests/test_veneer_errors.py::test_generic_exception_reaches_client_as_generic_message -v
```
Output:
```
tests/test_veneer_errors.py::test_curate_error_generic_exception_returns_generic_message PASSED
tests/test_veneer_errors.py::test_generic_exception_reaches_client_as_generic_message PASSED
2 passed in 0.03s
```

## AC-4

`serialize()` in `hearth/veneer/protocol.py` was not touched by this
feather (diff confirms only `curate_error`/`GENERIC_ERROR_MESSAGE` and an
added `BrainError` import were added; `serialize` itself is byte-for-byte
unchanged). The existing whitelist/forbidden-keys assertions in
`test_no_tool_internals_cross_boundary` (`tests/test_veneer.py`) and the
whitelist checks in `test_e2e_multiturn_chat_and_consult` /
`test_e2e_remote_tier_consult_same_shape` (`tests/test_e2e_veneer.py`)
still pass unchanged, alongside every other pre-existing test — full suite:

Command:
```
.venv/bin/python -m pytest -q
```
Output:
```
................................................ [100%]
48 passed in 0.54s
```
(42 pre-existing + 6 new from this feather, 0 regressions.)

## AC-5

`test_connection_closed_mid_turn_handled_cleanly` drives
`_handle_connection` with a fake websocket whose `send()` raises
`websockets.ConnectionClosed` while a reply is being sent (post-`run_turn`,
i.e. "mid-turn" from the client's perspective); asserts the call returns
without propagating and that `caplog` captured a clean record (no
`ERROR`-level record, an INFO record mentioning the disconnect) rather than
an unhandled-exception traceback.

`test_serve_continues_after_one_connection_disconnects`
(`tests/test_e2e_veneer.py`) drives this over a real `websockets.serve`
loopback server: connection 1 sends a turn and closes before the server's
reply lands (forcing `ConnectionClosed` out of `websocket.send` inside
`_handle_connection`), then connection 2 opens fresh and completes a normal
turn end-to-end against the same still-running server.

Implementation: `_handle_connection`'s per-message loop body is now wrapped
in `try/except websockets.ConnectionClosed: logger.info(...); return` at
the connection level; the inner per-turn `except Exception` block
re-raises `ConnectionClosed` first (`except websockets.ConnectionClosed:
raise`) so it isn't swallowed as a generic turn failure and instead
propagates to the outer handler, which logs at INFO and returns cleanly
instead of letting the exception escape `_handle_connection` uncaught.

Command:
```
.venv/bin/python -m pytest tests/test_veneer_errors.py::test_connection_closed_mid_turn_handled_cleanly tests/test_e2e_veneer.py::test_serve_continues_after_one_connection_disconnects -v
```
Output:
```
tests/test_veneer_errors.py::test_connection_closed_mid_turn_handled_cleanly PASSED
tests/test_e2e_veneer.py::test_serve_continues_after_one_connection_disconnects PASSED
2 passed in 0.42s
```

## Lint

```
$ ruff check .
All checks passed!
```
