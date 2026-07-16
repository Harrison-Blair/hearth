# FTHR-018 molt evidence: Connection category tagging

Note on test invocation: this worktree's venv has `hearth` installed
editable pointing at the **main checkout** (`/home/penguin/source/hearth`),
not this worktree. `<venv>/bin/pytest` (the console-script) does not put the
worktree's cwd ahead of that editable install on `sys.path`, so it silently
imports the main checkout's `hearth` package instead of this worktree's
changes. `<venv>/bin/python3 -m pytest` does put cwd first (matching normal
`python -m` behavior) and correctly imports this worktree's `hearth`. All
commands below use `python3 -m pytest` for that reason.

## AC-1: tests observed failing before implementation, passing after

Three tests were added test-first, run against the code as it stood after
FTHR-016 (before any FTHR-018 change):
- `tests/test_veneer_errors.py::test_connection_accepted_is_logged`
- `tests/test_veneer_errors.py::test_disconnect_and_malformed_frame_carry_category_tag`
- `tests/test_console_formatter.py::test_connection_category_gets_registered_coloring`

### Pre-implementation (FAILING) run

Command:
```
python3 -m pytest tests/test_veneer.py tests/test_veneer_errors.py tests/test_console_formatter.py -v
```

Output (verbatim, captured before any `hearth/veneer/server.py` or
`hearth/logging_setup.py` changes were made):
```
============================= test session starts ==============================
platform linux -- Python 3.14.6, pytest-9.1.1, pluggy-1.6.0 -- /home/penguin/source/hearth/.venv/bin/python3
cachedir: .pytest_cache
rootdir: /tmp/claude-1000/-home-penguin-source-hearth/f87e11cc-2fbb-4815-ae23-96a05fcf4a7b/scratchpad/FTHR-018
configfile: pyproject.toml
plugins: asyncio-1.4.0, anyio-4.14.1
asyncio: mode=Mode.AUTO, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collected 14 items

tests/test_veneer.py::test_veneer_roundtrip PASSED
tests/test_veneer.py::test_no_tool_internals_cross_boundary PASSED
tests/test_veneer.py::test_loop_error_maps_to_error_message PASSED
tests/test_veneer.py::test_malformed_frame_rejected_connection_survives PASSED
tests/test_veneer_errors.py::test_curate_error_brain_error_returns_reason PASSED
tests/test_veneer_errors.py::test_curate_error_generic_exception_returns_generic_message PASSED
tests/test_veneer_errors.py::test_brain_error_reaches_client_as_curated_reason PASSED
tests/test_veneer_errors.py::test_generic_exception_reaches_client_as_generic_message PASSED
tests/test_veneer_errors.py::test_connection_closed_mid_turn_handled_cleanly PASSED
tests/test_veneer_errors.py::test_connection_accepted_is_logged FAILED
tests/test_veneer_errors.py::test_disconnect_and_malformed_frame_carry_category_tag FAILED
tests/test_console_formatter.py::test_delimiter_present_in_every_line PASSED
tests/test_console_formatter.py::test_error_color_is_exclusive PASSED
tests/test_console_formatter.py::test_unknown_category_falls_back_to_level_only PASSED
tests/test_console_formatter.py::test_connection_category_gets_registered_coloring FAILED
tests/test_console_formatter.py::test_no_color_when_not_a_tty PASSED
tests/test_console_formatter.py::test_no_color_when_no_color_env_set PASSED
tests/test_console_formatter.py::test_file_handler_unaffected PASSED

=================================== FAILURES ===================================
____________________ test_connection_accepted_is_logged ____________________
    messages = [record.getMessage() for record in caplog.records]
    connect_idx = next((i for i, m in enumerate(messages) if "connected" in m.lower()), None)
    turn_idx = next((i for i, m in enumerate(messages) if m == "turn started"), None)
>   assert connect_idx is not None, f"no 'connected' log record found in {messages!r}"
E   AssertionError: no 'connected' log record found in ['turn started']
E   assert None is not None

tests/test_veneer_errors.py:175: AssertionError
------------------------------ Captured log call -------------------------------
INFO     test.turn:test_veneer_errors.py:161 turn started
______________ test_disconnect_and_malformed_frame_carry_category_tag ______________
    disconnect_records = [r for r in caplog.records if "disconnect" in r.getMessage().lower()]
    assert disconnect_records
>   assert all(getattr(r, "category", None) == "connection" for r in disconnect_records)
E   assert False
E    +  where False = all(<generator object test_disconnect_and_malformed_frame_carry_category_tag.<locals>.<genexpr> at ...>)

tests/test_veneer_errors.py:204: AssertionError
------------------------------ Captured log call -------------------------------
INFO     hearth.veneer.server:server.py:93 client disconnected mid-turn for session <uuid>
______________ test_connection_category_gets_registered_coloring ______________
    from hearth.logging_setup import _CATEGORY_COLORS, ColorFormatter
    monkeypatch.setattr("sys.stdout.isatty", lambda: True)
    monkeypatch.delenv("NO_COLOR", raising=False)
>   assert "connection" in _CATEGORY_COLORS
E   AssertionError: assert 'connection' in {}

tests/test_console_formatter.py:119: AssertionError
=========================== short test summary info ============================
FAILED tests/test_veneer_errors.py::test_connection_accepted_is_logged - AssertionError: no 'connected' log record found in ['turn started']
FAILED tests/test_veneer_errors.py::test_disconnect_and_malformed_frame_carry_category_tag - assert False
FAILED tests/test_console_formatter.py::test_connection_category_gets_registered_coloring - AssertionError: assert 'connection' in {}
======================= 3 failed, 11 passed in 0.05s =======================
```

All three fail for the expected reason: no connection-accepted log line
exists yet, the existing disconnect/malformed-frame lines carry no
`category`, and `"connection"` is not yet registered in `_CATEGORY_COLORS`.
The 11 pre-existing tests in these files (wire-whitelist, malformed-frame
survival, disconnect handling, formatter mechanics) pass unmodified,
confirming the failures are isolated to the new tests.

### Post-implementation (PASSING) run

Command:
```
python3 -m pytest tests/test_veneer.py tests/test_veneer_errors.py tests/test_console_formatter.py tests/test_logging.py -v
```

Output (verbatim, after implementing `hearth/veneer/server.py` and
`hearth/logging_setup.py`):
```
============================= test session starts ==============================
platform linux -- Python 3.14.6, pytest-9.1.1, pluggy-1.6.0 -- /home/penguin/source/hearth/.venv/bin/python3
cachedir: .pytest_cache
rootdir: /tmp/claude-1000/-home-penguin-source-hearth/f87e11cc-2fbb-4815-ae23-96a05fcf4a7b/scratchpad/FTHR-018
configfile: pyproject.toml
plugins: asyncio-1.4.0, anyio-4.14.1
asyncio: mode=Mode.AUTO, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collecting ... collected 27 items

tests/test_veneer.py::test_veneer_roundtrip PASSED                       [  3%]
tests/test_veneer.py::test_no_tool_internals_cross_boundary PASSED       [  7%]
tests/test_veneer.py::test_loop_error_maps_to_error_message PASSED       [ 11%]
tests/test_veneer.py::test_malformed_frame_rejected_connection_survives PASSED [ 14%]
tests/test_veneer_errors.py::test_curate_error_brain_error_returns_reason PASSED [ 18%]
tests/test_veneer_errors.py::test_curate_error_generic_exception_returns_generic_message PASSED [ 22%]
tests/test_veneer_errors.py::test_brain_error_reaches_client_as_curated_reason PASSED [ 25%]
tests/test_veneer_errors.py::test_generic_exception_reaches_client_as_generic_message PASSED [ 29%]
tests/test_veneer_errors.py::test_connection_closed_mid_turn_handled_cleanly PASSED [ 33%]
tests/test_veneer_errors.py::test_connection_accepted_is_logged PASSED   [ 37%]
tests/test_veneer_errors.py::test_disconnect_and_malformed_frame_carry_category_tag PASSED [ 40%]
tests/test_console_formatter.py::test_delimiter_present_in_every_line PASSED [ 44%]
tests/test_console_formatter.py::test_error_color_is_exclusive PASSED    [ 48%]
tests/test_console_formatter.py::test_unknown_category_falls_back_to_level_only PASSED [ 51%]
tests/test_console_formatter.py::test_connection_category_gets_registered_coloring PASSED [ 55%]
tests/test_console_formatter.py::test_no_color_when_not_a_tty PASSED     [ 59%]
tests/test_console_formatter.py::test_no_color_when_no_color_env_set PASSED [ 62%]
tests/test_console_formatter.py::test_file_handler_unaffected PASSED     [ 66%]
tests/test_logging.py::test_setup_logging_creates_rotating_handler PASSED [ 70%]
tests/test_logging.py::test_setup_logging_is_idempotent PASSED           [ 74%]
tests/test_logging.py::test_console_handler_streams_to_stdout PASSED     [ 77%]
tests/test_logging.py::test_console_handler_absent_when_disabled PASSED  [ 81%]
tests/test_logging.py::test_websockets_logger_routed_to_file PASSED      [ 85%]
tests/test_logging.py::test_websockets_logger_not_duplicated PASSED      [ 88%]
tests/test_logging.py::test_consult_turn_logs_both_models PASSED         [ 92%]
tests/test_logging.py::test_transcript_contains_ordered_turn_lines PASSED [ 96%]
tests/test_logging.py::test_logging_failure_does_not_crash_turn PASSED   [100%]

============================== 27 passed in 0.05s ===============================
```

## AC-2: new INFO connection-accepted log line, tagged `connection`, before any turn

`hearth/veneer/server.py::Veneer._handle_connection` now logs immediately
after `session_id = uuid.uuid4().hex` and before the `try`/`async for` loop
that processes turns:

```python
session_id = uuid.uuid4().hex
logger.info(
    "client connected session=%s", session_id, extra={"category": "connection"}
)
```

`test_connection_accepted_is_logged` (see AC-1 passing run above) proves
both the tag and the ordering: it drives `_handle_connection` with a loop
stub whose `run_turn` emits its own `"turn started"` log record, then
asserts the `"connected"` record's index in `caplog.records` is strictly
less than the `"turn started"` record's index, and that
`record.category == "connection"`.

## AC-3: existing disconnect / malformed-frame log calls carry `category=connection`, message/level unchanged

Diff (message text and level untouched, only `extra=` added):

```
-            logger.info("client disconnected mid-turn for session %s", session_id)
+            logger.info(
+                "client disconnected mid-turn for session %s",
+                session_id,
+                extra={"category": "connection"},
+            )
```

```
-                    logger.warning("rejecting malformed request frame for session %s", session_id)
+                    logger.warning(
+                        "rejecting malformed request frame for session %s",
+                        session_id,
+                        extra={"category": "connection"},
+                    )
```

`test_disconnect_and_malformed_frame_carry_category_tag` (see AC-1 passing
run) drives both scenarios (mid-turn `ConnectionClosed` on send, and a
malformed non-JSON frame) and asserts every resulting `LogRecord` whose
message contains "disconnect"/"malformed" has `record.category ==
"connection"`. Message text (`"client disconnected mid-turn for session
%s"` / `"rejecting malformed request frame for session %s"`) and level
(`INFO`/`WARNING`) are unchanged from the pre-FTHR-018 code.

## AC-4: `connection` category renders distinctly, never reuses the reserved ERROR/CRITICAL color

`hearth/logging_setup.py` registers, as a single appended statement (per
the shared-file convention for this dict, since FTHR-019 concurrently adds
a `"server"` entry):

```python
_CATEGORY_COLORS["connection"] = lambda message: f"\x1b[36m{message}\x1b[0m"
```

(cyan `\x1b[36m`, distinct from the reserved bold-red `\x1b[1;31m` used
exclusively for ERROR/CRITICAL.)

`test_connection_category_gets_registered_coloring` (see AC-1 passing run)
asserts: `"connection"` is registered in `_CATEGORY_COLORS`; a
`connection`-tagged INFO line renders differently from the same message
uncategorized (color applied); and the ANSI codes it emits share no overlap
with the ANSI codes an ERROR-level line emits (the reserved color is never
reused). `test_error_color_is_exclusive` in the same file (pre-existing,
passing above) independently re-checks every registered category
(including `connection`, once registered) against the same
never-reuse-the-error-color invariant.

## AC-5: existing wire-whitelist and connection-behavior tests pass unmodified

From both the pre- and post-implementation runs above,
`tests/test_veneer.py`'s four tests (including
`test_no_tool_internals_cross_boundary`, which asserts the
`forbidden_keys`/whitelist wire contract, and
`test_malformed_frame_rejected_connection_survives`) pass unchanged in both
runs -- no test assertions in `test_veneer.py` were touched by this
feather. Full repo suite, post-implementation:

```
python3 -m pytest -q
........................................................................ [ 83%]
..............                                                           [100%]
86 passed in 0.80s
```
