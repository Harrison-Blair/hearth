# FTHR-017 molt evidence — Metrics category tagging

Test invocation used throughout (run from the worktree root, per the
orchestrator's instruction — the editable install otherwise resolves
`hearth` against main's copy):

```
/home/penguin/source/hearth/.venv/bin/python -m pytest
```

## AC-1: The tests listed above were observed failing before implementation and pass after.

Four tests were written test-first, named per the feather's Tests section
(one per named test plus a companion timeout-marker test that AC-2 also
requires — see AC-2 note):

- `tests/test_loop.py::test_metrics_calls_carry_category_tag` (spec's
  `test_metrics_calls_carry_category_tag`)
- `tests/test_loop.py::test_failed_marker_carries_category_tag` (spec's
  `test_failed_marker_carries_category_tag`, covering the `BrainError`
  FAILED marker)
- `tests/test_loop_tools.py::test_timeout_marker_carries_category_tag`
  (companion test covering the turn-timeout WARNING marker also named by
  AC-2 — the spec's "FAILED marker" test names the `BrainError` case
  explicitly; this extends the same assertion to the timeout marker so both
  halves of AC-2's "FAILED/timeout-marker" wording are covered)
- `tests/test_console_formatter.py::test_metrics_category_gets_registered_coloring`
  (spec's `test_metrics_category_gets_registered_coloring`)

### Pre-implementation run (unchanged code — `logging_setup.py`'s
`_CATEGORY_COLORS` has no `"metrics"` entry yet, and none of the FTHR-013/014
log calls in `loop.py` pass `extra={"category": ...}`):

```
$ /home/penguin/source/hearth/.venv/bin/python -m pytest tests/test_loop.py::test_metrics_calls_carry_category_tag tests/test_loop.py::test_failed_marker_carries_category_tag tests/test_loop_tools.py::test_timeout_marker_carries_category_tag tests/test_console_formatter.py::test_metrics_category_gets_registered_coloring -v
============================= test session starts ==============================
platform linux -- Python 3.14.6, pytest-9.1.1, pluggy-1.6.0 -- /home/penguin/source/hearth/.venv/bin/python
cachedir: .pytest_cache
rootdir: /tmp/claude-1000/-home-penguin-source-hearth/f87e11cc-2fbb-4815-ae23-96a05fcf4a7b/scratchpad/FTHR-017
configfile: pyproject.toml
plugins: asyncio-1.4.0, anyio-4.14.1
asyncio: mode=Mode.AUTO, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collecting ... collected 4 items

tests/test_loop.py::test_metrics_calls_carry_category_tag FAILED         [ 25%]
tests/test_loop.py::test_failed_marker_carries_category_tag FAILED       [ 50%]
tests/test_loop_tools.py::test_timeout_marker_carries_category_tag FAILED [ 75%]
tests/test_console_formatter.py::test_metrics_category_gets_registered_coloring FAILED [100%]

=================================== FAILURES ===================================
____________________ test_metrics_calls_carry_category_tag _____________________
...
        assert call_records
>       assert call_records[0].category == "metrics"
               ^^^^^^^^^^^^^^^^^^^^^^^^
E       AttributeError: 'LogRecord' object has no attribute 'category'

tests/test_loop.py:208: AttributeError
------------------------------ Captured log call -------------------------------
INFO     httpx:_client.py:1740 HTTP Request: POST http://localhost:11434/v1/chat/completions "HTTP/1.1 200 OK"
INFO     hearth.loop:loop.py:61 llm call tier=default model=qwen3:14b round=1 in=12 out=6 thinking=n/a duration_s=0.0s tok/s=15356.6
INFO     hearth.loop:loop.py:250 turn summary turn=1 rounds=1 calls=1 in=12 out=6 duration_s=0.0s tok/s=15356.6
___________________ test_failed_marker_carries_category_tag ____________________
...
        failed_records = [r for r in caplog.records if "FAILED" in r.getMessage()]
        assert failed_records
>       assert failed_records[0].category == "metrics"
               ^^^^^^^^^^^^^^^^^^^^^^^^^^
E       AttributeError: 'LogRecord' object has no attribute 'category'

tests/test_loop.py:234: AttributeError
------------------------------ Captured log call -------------------------------
WARNING  hearth.loop:loop.py:81 llm call tier=default round=1 FAILED reason=backend error after=0.0s
___________________ test_timeout_marker_carries_category_tag ___________________
...
        warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
        timeout_records = [r for r in warning_records if "timeout" in r.getMessage().lower()]
        assert timeout_records
>       assert timeout_records[0].category == "metrics"
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^
E       AttributeError: 'LogRecord' object has no attribute 'category'

tests/test_loop_tools.py:531: AttributeError
------------------------------ Captured log call -------------------------------
WARNING  hearth.loop:loop.py:363 turn timeout tier=default after=0.1s
________________ test_metrics_category_gets_registered_coloring ________________
...
>       assert "metrics" in _CATEGORY_COLORS
E       AssertionError: assert 'metrics' in {'connection': <function <lambda> at 0x7ff6e95d57a0>, 'server': <function <lambda> at 0x7ff6e95d56f0>}

tests/test_console_formatter.py:182: AssertionError
=========================== short test summary info ============================
FAILED tests/test_loop.py::test_metrics_calls_carry_category_tag - AttributeE...
FAILED tests/test_loop.py::test_failed_marker_carries_category_tag - Attribut...
FAILED tests/test_loop_tools.py::test_timeout_marker_carries_category_tag - A...
FAILED tests/test_console_formatter.py::test_metrics_category_gets_registered_coloring
============================== 4 failed in 0.09s ===============================
```

Each failure is for the expected reason: `record.category` doesn't exist
because no call site passes `extra={"category": ...}` yet (three tests), and
`"metrics"` isn't registered in `_CATEGORY_COLORS` yet (the fourth). No
setup/collection errors, no unrelated failures.

### Post-implementation run (same 4 tests, after implementing):

```
$ /home/penguin/source/hearth/.venv/bin/python -m pytest tests/test_loop.py::test_metrics_calls_carry_category_tag tests/test_loop.py::test_failed_marker_carries_category_tag tests/test_loop_tools.py::test_timeout_marker_carries_category_tag tests/test_console_formatter.py::test_metrics_category_gets_registered_coloring -v
============================= test session starts ==============================
platform linux -- Python 3.14.6, pytest-9.1.1, pluggy-1.6.0 -- /home/penguin/source/hearth/.venv/bin/python
cachedir: .pytest_cache
rootdir: /tmp/claude-1000/-home-penguin-source-hearth/f87e11cc-2fbb-4815-ae23-96a05fcf4a7b/scratchpad/FTHR-017
configfile: pyproject.toml
plugins: asyncio-1.4.0, anyio-4.14.1
asyncio: mode=Mode.AUTO, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collecting ... collected 4 items

tests/test_loop.py::test_metrics_calls_carry_category_tag PASSED         [ 25%]
tests/test_loop.py::test_failed_marker_carries_category_tag PASSED       [ 50%]
tests/test_loop_tools.py::test_timeout_marker_carries_category_tag PASSED [ 75%]
tests/test_console_formatter.py::test_metrics_category_gets_registered_coloring PASSED [100%]

============================== 4 passed in 0.07s ===============================
```

### Full suite (no regressions):

```
$ /home/penguin/source/hearth/.venv/bin/python -m pytest
============================= test session starts ==============================
platform linux -- Python 3.14.6, pytest-9.1.1, pluggy-1.6.0
rootdir: /tmp/claude-1000/-home-penguin-source-hearth/f87e11cc-2fbb-4815-ae23-96a05fcf4a7b/scratchpad/FTHR-017
configfile: pyproject.toml
plugins: asyncio-1.4.0, anyio-4.14.1
asyncio: mode=Mode.AUTO, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collected 103 items

tests/test_app.py ....                                                   [  3%]
tests/test_brain_errors.py .....                                         [  8%]
tests/test_brain_guard.py ..                                             [ 10%]
tests/test_config.py ..........                                          [ 20%]
tests/test_console_formatter.py .........                                [ 29%]
tests/test_consult_brain.py .....                                        [ 33%]
tests/test_e2e_veneer.py ....                                            [ 37%]
tests/test_event_log.py .                                                [ 38%]
tests/test_layer2_reader.py ...                                          [ 41%]
tests/test_local_backend.py .........                                    [ 50%]
tests/test_logging.py .........                                          [ 59%]
tests/test_loop.py .......                                               [ 66%]
tests/test_loop_tools.py ..........                                      [ 75%]
tests/test_orchestrator_persona.py ..                                    [ 77%]
tests/test_remote_backend.py ..                                          [ 79%]
tests/test_router.py ....                                                [ 83%]
tests/test_veneer.py ....                                                [ 87%]
tests/test_veneer_client.py ..                                           [ 89%]
tests/test_veneer_errors.py .......                                      [ 96%]
tests/test_wikipedia.py ....                                             [100%]

============================= 103 passed in 0.94s ==============================
```

`ruff check` on the touched files also passes clean:

```
$ /home/penguin/source/hearth/.venv/bin/python -m ruff check hearth/loop.py hearth/logging_setup.py tests/test_loop.py tests/test_loop_tools.py tests/test_console_formatter.py
All checks passed!
```

## AC-2: Every per-call, per-turn, and FAILED/timeout-marker log call from FTHR-013/FTHR-014 carries `extra={"category": "metrics"}`, with no change to message text or log level. Satisfies PLM-004 FC-4.

`hearth/loop.py` — every FTHR-013/FTHR-014 log call now passes
`extra={"category": "metrics"}`; message text and level are byte-for-byte
unchanged (verified by diff below and by the pre-existing message-content
assertions in `test_loop_logs_per_call_and_per_turn_metrics`,
`test_loop_logs_failed_marker_on_brain_error_never_leaks_detail`, and
`test_turn_timeout_logs_marker_and_counts_failed_call`, all of which still
pass unmodified — see full-suite run above):

```diff
--- a/hearth/loop.py
+++ b/hearth/loop.py
@@ _log_call_metrics (per-call INFO, FTHR-013)
             duration_str,
             tokens_per_s,
+            extra={"category": "metrics"},
         )
@@ _log_failed_call_marker (FAILED WARNING, FTHR-014)
             reason,
             elapsed,
+            extra={"category": "metrics"},
         )
@@ Loop._log_turn_metrics (per-turn summary INFO, FTHR-013)
                 duration_s,
                 tokens_per_s,
+                extra={"category": "metrics"},
             )
@@ Loop.run_turn's except asyncio.TimeoutError handler ("turn timeout" WARNING, FTHR-014)
-                logger.warning(
-                    "turn timeout tier=%s after=%.1fs", selection.tier, elapsed
-                )
+                logger.warning(
+                    "turn timeout tier=%s after=%.1fs",
+                    selection.tier,
+                    elapsed,
+                    extra={"category": "metrics"},
+                )
```

(The last hunk only reflows the call across more lines to fit the new
kwarg — the format string and its two positional args are unchanged.)

`hearth/brain/openai_compat.py` — confirmed no direct `logger.*` calls exist
in this module (`grep -n "logger\." hearth/brain/openai_compat.py` returns
nothing); FTHR-013's per-call logging lives solely in
`run_react_rounds`/`hearth/loop.py` per its own Approach section, so no
changes were needed here, matching the feather's own caveat ("this file may
need no changes").

Covered by:
- `test_metrics_calls_carry_category_tag` (per-call + per-turn INFO lines)
- `test_failed_marker_carries_category_tag` (FAILED WARNING marker)
- `test_timeout_marker_carries_category_tag` (turn-timeout WARNING marker)
- The full suite's still-passing FTHR-013/014 message-content tests prove no
  text/level regression.

## AC-3: The console formatter's `metrics` category renders these lines with distinguishable per-segment coloring that never reuses the reserved ERROR/CRITICAL color, completing PLM-004 AC-3's metrics-category coverage (FTHR-016 covers the fallback/registry mechanism; this feather completes the `metrics` case).

`hearth/logging_setup.py` registers `_CATEGORY_COLORS["metrics"]` via a
single appended statement (`_CATEGORY_COLORS["metrics"] = _colorize_metrics`),
following the same append pattern as FTHR-018's `"connection"` and
FTHR-019's `"server"` entries. `_colorize_metrics` applies **per-segment**
coloring (not a single color wrapping the whole message, unlike
`connection`/`server`): green (`\x1b[32m`) for the token-count segments
(`in=`, `out=`, `thinking=`) and blue (`\x1b[34m`) for the timing segments
(`duration_s=`, `tok/s=`, `after=`) — both distinct from `connection`'s cyan
(`\x1b[36m`), `server`'s magenta (`\x1b[35m`), and the reserved
ERROR/CRITICAL bold red (`\x1b[1;31m`).

`test_metrics_category_gets_registered_coloring`
(`tests/test_console_formatter.py`) formats a real metrics-shaped log line
(`"llm call tier=default model=x round=1 in=12 out=6 thinking=n/a
duration_s=1.2s tok/s=5.0"`) through `ColorFormatter` with `category="metrics"`
and color forced on, and asserts:
- the metrics-tagged output carries ANSI codes the plain/uncategorized
  rendering of the same message does not (`metrics_codes` non-empty and
  `!= plain_codes`);
- at least two distinct ANSI codes appear (`len(metrics_codes) >= 2`),
  proving per-segment (not single-color) coloring;
- none of the metrics codes equal the reserved ERROR/CRITICAL code
  (`\x1b[1;31m`);
- none of the metrics codes intersect the `connection` category's codes or
  the `server` category's codes on the same message (the regression pin the
  orchestrator's spawn prompt called out, mirroring FTHR-019's
  server-!=-connection pin).

Passing run captured above (post-implementation section of AC-1) and in the
full-suite run (`tests/test_console_formatter.py .........` — 9/9 passing,
including this new test and all of FTHR-016/018/019's pre-existing coloring
tests, unmodified).
