# FTHR-019 evidence: Server category tagging

## AC-1

Tests written test-first in `tests/test_app.py`
(`test_run_daemon_logs_server_lifecycle_lines`) and
`tests/test_console_formatter.py`
(`test_server_category_gets_registered_coloring`).

### Pre-implementation run (FAILING, captured before touching `hearth/app.py` / `hearth/logging_setup.py`)

```
$ .venv/bin/pytest tests/test_app.py::test_run_daemon_logs_server_lifecycle_lines tests/test_console_formatter.py::test_server_category_gets_registered_coloring -v
collecting ... collected 2 items

tests/test_app.py::test_run_daemon_logs_server_lifecycle_lines FAILED    [ 50%]
tests/test_console_formatter.py::test_server_category_gets_registered_coloring FAILED [100%]

=================================== FAILURES ===================================
_________________ test_run_daemon_logs_server_lifecycle_lines __________________
...
    assert exit_code == 0
    server_records = [r for r in caplog.records if getattr(r, "category", None) == "server"]
    messages = [r.getMessage() for r in server_records]
>       assert any("daemon starting" in m for m in messages)
E       assert False
E        +  where False = any(<generator object test_run_daemon_logs_server_lifecycle_lines.<locals>.<genexpr> at 0x7f141b6c9080>)

/tmp/claude-1000/-home-penguin-source-hearth/f87e11cc-2fbb-4815-ae23-96a05fcf4a7b/scratchpad/FTHR-019/tests/test_app.py:83: AssertionError
________________ test_server_category_gets_registered_coloring _________________
...
    assert "server" in _CATEGORY_COLORS
E       AssertionError: assert 'server' in {}

tests/test_console_formatter.py:118: AssertionError
=========================== short test summary info ============================
FAILED tests/test_app.py::test_run_daemon_logs_server_lifecycle_lines - asser...
FAILED tests/test_console_formatter.py::test_server_category_gets_registered_coloring
============================== 2 failed in 0.07s ===============================
```

Both fail for the expected reason: `_run_daemon()` has no logger calls yet
(no `category="server"` records are ever emitted), and `_CATEGORY_COLORS`
has no `"server"` entry yet (it is empty — FTHR-017/018 hadn't landed at
capture time either).

### Post-implementation run (PASSING)

Note: invoked as `.venv/bin/python -m pytest` rather than `.venv/bin/pytest` --
in this worktree `.venv` is a symlink to the main checkout's venv (editable
install), and the bare console-script entry point resolves `sys.path[0]` to
the script's own directory rather than the cwd, which would silently pick up
the main checkout's `hearth/` instead of this worktree's. `python -m pytest`
puts the cwd first, correctly exercising this worktree's source.

```
$ .venv/bin/python -m pytest tests/test_app.py tests/test_console_formatter.py -v
============================= test session starts ==============================
collected 11 items

tests/test_app.py::test_build_llm_clients_wires_configured_timeout PASSED [  9%]
tests/test_app.py::test_version_command PASSED                           [ 18%]
tests/test_app.py::test_run_daemon_wires_wikipedia_tool_brain_side PASSED [ 27%]
tests/test_app.py::test_run_daemon_logs_server_lifecycle_lines PASSED    [ 36%]
tests/test_console_formatter.py::test_delimiter_present_in_every_line PASSED [ 45%]
tests/test_console_formatter.py::test_error_color_is_exclusive PASSED    [ 54%]
tests/test_console_formatter.py::test_unknown_category_falls_back_to_level_only PASSED [ 63%]
tests/test_console_formatter.py::test_server_category_gets_registered_coloring PASSED [ 72%]
tests/test_console_formatter.py::test_no_color_when_not_a_tty PASSED     [ 81%]
tests/test_console_formatter.py::test_no_color_when_no_color_env_set PASSED [ 90%]
tests/test_console_formatter.py::test_file_handler_unaffected PASSED     [100%]

============================== 11 passed in 0.07s ==============================
```

Full suite:

```
$ .venv/bin/python -m pytest -q
........................................................................ [ 84%]
.............                                                            [100%]
85 passed in 0.81s
```

`ruff check` on all touched files: `All checks passed!`

## AC-2

`_run_daemon()` now has a module-level `logger = logging.getLogger(__name__)`
in `hearth/app.py`, and emits:
- `logger.info("hearth daemon starting", extra={"category": "server"})`
  right after `setup_logging(settings.logging)`.
- `logger.info("veneer serving host=%s port=%s", settings.veneer.host, settings.veneer.port, extra={"category": "server"})`
  right before `await veneer.serve(...)`.

No control-flow change: verified by `test_run_daemon_wires_wikipedia_tool_brain_side`
passing unmodified (same object wiring / return value assertions).

## AC-3

`hearth/logging_setup.py` registers `_CATEGORY_COLORS["server"] = ...` with
a coloring function distinct from the reserved ERROR/CRITICAL bold-red code.
Verified by `test_server_category_gets_registered_coloring`.

## AC-4

`test_version_command` and `test_run_daemon_wires_wikipedia_tool_brain_side`
pass unmodified post-implementation (see full suite run below).
