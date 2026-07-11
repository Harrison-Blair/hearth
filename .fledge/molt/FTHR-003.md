# FTHR-003 molt evidence

## AC-1

Tests written test-first per the spec's Tests section
(`tests/test_veneer.py`: `test_veneer_roundtrip`,
`test_no_tool_internals_cross_boundary`, `test_loop_error_maps_to_error_message`),
run against the unimplemented `hearth.veneer` package (only `hearth/veneer/__init__.py`
existed, no `protocol.py`/`server.py`/`client.py`).

Command:

```
.venv/bin/python -m pytest tests/test_veneer.py -v
```

Captured output (FAILING, verbatim):

```
============================= test session starts ==============================
platform linux -- Python 3.14.6, pytest-9.1.1, pluggy-1.6.0 -- /home/penguin/source/hearth/.fledge/burrows/FTHR-003/.venv/bin/python
cachedir: .pytest_cache
rootdir: /home/penguin/source/hearth/.fledge/burrows/FTHR-003
configfile: pyproject.toml
plugins: asyncio-1.4.0, anyio-4.14.1
asyncio: mode=Mode.AUTO, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collecting ... collected 0 items / 1 error

==================================== ERRORS ====================================
____________________ ERROR collecting tests/test_veneer.py _____________________
ImportError while importing test module '/home/penguin/source/hearth/.fledge/burrows/FTHR-003/tests/test_veneer.py'.
Hint: make sure your test modules/packages have valid Python names.
Traceback:
/usr/lib/python3.14/importlib/__init__.py:88: in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
tests/test_veneer.py:12: in <module>
    from hearth.veneer.client import send_turn
E   ModuleNotFoundError: No module named 'hearth.veneer.client'
=========================== short test summary info ============================
ERROR tests/test_veneer.py
!!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
=============================== 1 error in 0.05s ===============================
```

Failure is for the expected reason: `hearth/veneer/protocol.py`, `server.py`,
`client.py` did not exist yet (only the package `__init__.py`). Implementation
follows below; post-implementation passing run captured under AC-2.

Post-implementation (all three tests green):

```
$ .venv/bin/python -m pytest tests/test_veneer.py -v
============================= test session starts ==============================
platform linux -- Python 3.14.6, pytest-9.1.1, pluggy-1.6.0 -- .../.venv/bin/python
plugins: asyncio-1.4.0, anyio-4.14.1
asyncio: mode=Mode.AUTO, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collecting ... collected 3 items

tests/test_veneer.py::test_veneer_roundtrip PASSED                       [ 33%]
tests/test_veneer.py::test_no_tool_internals_cross_boundary PASSED       [ 66%]
tests/test_veneer.py::test_loop_error_maps_to_error_message PASSED       [100%]

============================== 3 passed in 0.02s ===============================
```

## AC-2

`test_veneer_roundtrip` (see AC-1 passing output above) drives `Veneer` over a
real loopback WebSocket (`websockets.connect`/`websockets.serve`, ephemeral
port), sends `{turn_id, final_user_transcript}`, and asserts the two inbound
messages are `{"type": "answer", "turn_id": <same turn_id>, "text": ...}`
then `{"type": "done", "turn_id": <same turn_id>}` — i.e. zero-or-more
`tool_activity`, one `answer`, one terminal `done`, all tagged with the
request's `turn_id`. `test_no_tool_internals_cross_boundary` additionally
confirms two `tool_activity` messages precede `answer`/`done` when the turn
emits activity. `test_loop_error_maps_to_error_message` confirms the `error`
terminal case. The turn's `user_input`/`final_answer` log events are asserted
directly against the shared `EventLog` in `test_veneer_roundtrip`
(`_event_types(log) == ["user_input", "final_answer"]`).

Implements: `hearth/veneer/protocol.py` (`Request`, `parse_request`,
`answer_message`, `done_message`, `error_message`), `hearth/veneer/server.py`
(`Veneer._handle_connection`).

## AC-3

`hearth run` now constructs `EventLog`, `Router`, `Loop`, and `Veneer` from
`Settings` and serves the contract (`hearth/app.py:_run_daemon`), replacing
FTHR-001's stub. Manual end-to-end smoke test against the built console
script + the trivial text client, run from the worktree root
(`config.yaml`'s default LLM backend points at a local Ollama not running in
this sandbox, so the turn takes the error path — this still proves the
daemon accepts a real client connection over the real socket and completes a
turn to a terminal wire message, exercising the same server code path as
AC-2's automated tests, which cover the successful-answer terminal case):

```
$ (.venv/bin/hearth run > /tmp/hearth_run.log 2>&1 &) && sleep 1
$ echo "hello there" | .venv/bin/python -m hearth.veneer.client
error: the turn failed
$ pkill -f "hearth run"
```

`/tmp/hearth_run.log` was empty (no crash/traceback) — the daemon started
cleanly, accepted the connection, and logged nothing to stderr; the `error`
the client printed came from the wire `error{message}` the failing
`Loop.run_turn` (an unreachable `http://localhost:11434/v1`) produced, per
AC-5's contract, not a daemon crash.

Combined with `test_veneer_roundtrip` (AC-2, automated, successful-answer
path) this covers AC-3: the daemon serves the contract and the trivial text
client completes a turn against it, both on the happy path (automated test)
and as an actual OS-level process + socket (manual smoke test above).

## AC-4

`test_no_tool_internals_cross_boundary` (see AC-2) makes a turn emit two
`ToolActivity` events and asserts, for every one of the 4 outbound wire
messages of the turn (`tool_activity`, `tool_activity`, `answer`, `done`):
its keys are a subset of a fixed per-type whitelist, and none of
`{"query", "arguments", "observation", "result"}` appear as a key.

This is structural, not conventional: `hearth/veneer/protocol.py:serialize`
only accepts `ToolActivity` (`isinstance` check) and builds the wire dict by
naming exactly two fields off it (`event.phase`, `event.label`) — there is no
code path that could forward `hearth.events.ToolActivity`'s other fields
(there are none besides `turn_id`/`phase`/`label` — see `hearth/events.py`)
or any other event type; any other event type raises `TypeError` instead of
serializing. `Veneer._handle_connection`'s `sink` calls only `serialize`, so
nothing bypasses the whitelist on the way to the socket.

## AC-5

`test_loop_error_maps_to_error_message` makes `Loop.run_turn` raise
`RuntimeError("boom: leaked internal detail")` and asserts: exactly one
outbound message, `type == "error"`, and neither `"boom"` nor
`"leaked internal detail"` appear anywhere in `message["message"]`; and that
an `"error"`-typed row was appended to the `EventLog`.

Implementation: `Veneer._handle_connection`'s `except Exception` branch
(`hearth/veneer/server.py`) appends `{"message": str(exc)}` to the log with
`provenance="loop"` (the failing stage — currently the only stage that can
raise, since FTHR-006 hasn't added tool rounds/observations yet), then sends
a fixed, generic `error_message(turn_id, "the turn failed")` over the wire —
the exception's `str()` never reaches the socket. The manual smoke test
under AC-3 exercises this same path against a real, unreachable backend.
