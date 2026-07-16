# FTHR-014 molt evidence — Failure and timeout metrics markers

Test invocation used throughout (per orchestrator instructions — worktree root,
NOT the editable-install console script):

```
/home/penguin/source/hearth/.venv/bin/python -m pytest ...
```

## AC-1: The tests listed above were observed failing before implementation and pass after.

Four new tests were written test-first, one per failure/timeout scenario named in the
feather's Tests section:

- `tests/test_loop.py::test_loop_logs_failed_marker_on_brain_error_never_leaks_detail`
- `tests/test_loop_tools.py::test_turn_summary_counts_failed_nested_consult_call`
- `tests/test_loop_tools.py::test_turn_timeout_logs_marker_and_counts_failed_call`
- `tests/test_consult_brain.py::test_consult_timeout_logs_marker`

**FAILING run, captured against the unmodified (FTHR-013-only) code, before any
implementation changes:**

```
$ /home/penguin/source/hearth/.venv/bin/python -m pytest tests/test_loop.py::test_loop_logs_failed_marker_on_brain_error_never_leaks_detail tests/test_loop_tools.py::test_turn_summary_counts_failed_nested_consult_call tests/test_loop_tools.py::test_turn_timeout_logs_marker_and_counts_failed_call tests/test_consult_brain.py::test_consult_timeout_logs_marker -v

============================= test session starts ==============================
platform linux -- Python 3.14.6, pytest-9.1.1, pluggy-1.6.0 -- /home/penguin/source/hearth/.venv/bin/python
cachedir: .pytest_cache
rootdir: /tmp/claude-1000/-home-penguin-source-hearth/f87e11cc-2fbb-4815-ae23-96a05fcf4a7b/scratchpad/FTHR-014
configfile: pyproject.toml
plugins: asyncio-1.4.0, anyio-4.14.1
asyncio: mode=Mode.AUTO, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collecting ... collected 4 items

tests/test_loop.py::test_loop_logs_failed_marker_on_brain_error_never_leaks_detail FAILED [ 25%]
tests/test_loop_tools.py::test_turn_summary_counts_failed_nested_consult_call FAILED [ 50%]
tests/test_loop_tools.py::test_turn_timeout_logs_marker_and_counts_failed_call FAILED [ 75%]
tests/test_consult_brain.py::test_consult_timeout_logs_marker FAILED     [100%]

=================================== FAILURES ===================================
________ test_loop_logs_failed_marker_on_brain_error_never_leaks_detail ________
    ...
    with pytest.raises(BrainError) as excinfo:
        await loop.run_turn("s1", "t1", "hello")

    assert secret_body in excinfo.value.detail  # sanity: detail really carries it

    messages = [record.getMessage() for record in caplog.records]
    failed_lines = [m for m in messages if "FAILED" in m]
>   assert failed_lines, messages
E   AssertionError: []
E   assert []

tests/test_loop.py:170: AssertionError
_____________ test_turn_summary_counts_failed_nested_consult_call ______________
    ...
    messages = [record.getMessage() for record in caplog.records]

    failed_lines = [m for m in messages if "FAILED" in m]
>   assert failed_lines, messages
E   AssertionError: ['HTTP Request: POST http://local-llm.test/v1/chat/completions "HTTP/1.1 200 OK"', 'llm call tier=default model=qwen3:14b round=1 in=10 out=4 thinking=n/a duration_s=0.0s tok/s=15597.6', 'HTTP Request: POST https://remote-llm.test/v1/chat/completions "HTTP/1.1 200 OK"', 'HTTP Request: POST http://local-llm.test/v1/chat/completions "HTTP/1.1 200 OK"', 'llm call tier=default model=qwen3:14b round=2 in=20 out=8 thinking=n/a duration_s=0.0s tok/s=57203.7', 'turn summary turn=1 rounds=2 calls=2 in=30 out=12 duration_s=0.0s tok/s=30280.0']
E   assert []

tests/test_loop_tools.py:455: AssertionError
------------------------------ Captured log call -------------------------------
INFO     httpx:_client.py:1740 HTTP Request: POST http://local-llm.test/v1/chat/completions "HTTP/1.1 200 OK"
INFO     hearth.loop:loop.py:55 llm call tier=default model=qwen3:14b round=1 in=10 out=4 thinking=n/a duration_s=0.0s tok/s=15597.6
INFO     httpx:_client.py:1740 HTTP Request: POST https://remote-llm.test/v1/chat/completions "HTTP/1.1 200 OK"
INFO     httpx:_client.py:1740 HTTP Request: POST http://local-llm.test/v1/chat/completions "HTTP/1.1 200 OK"
INFO     hearth.loop:loop.py:55 llm call tier=default model=qwen3:14b round=2 in=20 out=8 thinking=n/a duration_s=0.0s tok/s=57203.7
INFO     hearth.loop:loop.py:199 turn summary turn=1 rounds=2 calls=2 in=30 out=12 duration_s=0.0s tok/s=30280.0
_____________ test_turn_timeout_logs_marker_and_counts_failed_call _____________
    ...
    messages = [record.getMessage() for record in caplog.records]
    warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
    timeout_lines = [r.getMessage() for r in warning_records if "timeout" in r.getMessage().lower()]
>   assert timeout_lines, messages
E   AssertionError: ['HTTP Request: POST http://local-llm.test/v1/chat/completions "HTTP/1.1 200 OK"', 'llm call tier=default model=qwen3:14b round=1 in=None out=None thinking=n/a duration_s=0.0s tok/s=n/a', 'turn summary turn=1 rounds=0 calls=0 in=0 out=0 duration_s=0.0s tok/s=n/a']
E   assert []

tests/test_loop_tools.py:499: AssertionError
------------------------------ Captured log call -------------------------------
INFO     httpx:_client.py:1740 HTTP Request: POST http://local-llm.test/v1/chat/completions "HTTP/1.1 200 OK"
INFO     hearth.loop:loop.py:55 llm call tier=default model=qwen3:14b round=1 in=None out=None thinking=n/a duration_s=0.0s tok/s=n/a
INFO     hearth.loop:loop.py:199 turn summary turn=1 rounds=0 calls=0 in=0 out=0 duration_s=0.0s tok/s=n/a
_______________________ test_consult_timeout_logs_marker _______________________
    ...
    messages = [record.getMessage() for record in caplog.records]
    timeout_lines = [m for m in messages if "timeout" in m.lower()]
>   assert timeout_lines, messages
E   AssertionError: []
E   assert []

tests/test_consult_brain.py:221: AssertionError
=========================== short test summary info ============================
FAILED tests/test_loop.py::test_loop_logs_failed_marker_on_brain_error_never_leaks_detail
FAILED tests/test_loop_tools.py::test_turn_summary_counts_failed_nested_consult_call
FAILED tests/test_loop_tools.py::test_turn_timeout_logs_marker_and_counts_failed_call
FAILED tests/test_consult_brain.py::test_consult_timeout_logs_marker - Assert...
============================== 4 failed in 0.10s ===============================
```

All four failed for the expected reason: no `FAILED`/`timeout` marker existed yet in
`hearth/loop.py`/`hearth/tools/consult.py`, so the assertions on `caplog` content found
nothing (or, for the first test, the same underlying gap — no `FAILED` line — while the
`pytest.raises(BrainError)` half of that test already passed against unmodified code,
since propagation was already correct pre-feature).

**PASSING run, after implementation (`hearth/loop.py`, `hearth/tools/consult.py`):**

```
$ /home/penguin/source/hearth/.venv/bin/python -m pytest tests/test_loop.py::test_loop_logs_failed_marker_on_brain_error_never_leaks_detail tests/test_loop_tools.py::test_turn_summary_counts_failed_nested_consult_call tests/test_loop_tools.py::test_turn_timeout_logs_marker_and_counts_failed_call tests/test_consult_brain.py::test_consult_timeout_logs_marker -v

============================= test session starts ==============================
platform linux -- Python 3.14.6, pytest-9.1.1, pluggy-1.6.0 -- /home/penguin/source/hearth/.venv/bin/python
cachedir: .pytest_cache
rootdir: /tmp/claude-1000/-home-penguin-source-hearth/f87e11cc-2fbb-4815-ae23-96a05fcf4a7b/scratchpad/FTHR-014
configfile: pyproject.toml
plugins: asyncio-1.4.0, anyio-4.14.1
asyncio: mode=Mode.AUTO, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collecting ... collected 4 items

tests/test_loop.py::test_loop_logs_failed_marker_on_brain_error_never_leaks_detail PASSED [ 25%]
tests/test_loop_tools.py::test_turn_summary_counts_failed_nested_consult_call PASSED [ 50%]
tests/test_loop_tools.py::test_turn_timeout_logs_marker_and_counts_failed_call PASSED [ 75%]
tests/test_consult_brain.py::test_consult_timeout_logs_marker PASSED     [100%]

============================== 4 passed in 0.08s ===============================
```

## AC-2: `BrainError` from `brain.complete()` inside `run_react_rounds` produces a FAILED marker (tier, round, `.reason`, elapsed) at WARNING, before propagating unchanged, and never logs `.detail`.

Implemented in `hearth/loop.py`: `run_react_rounds` now wraps both `brain.complete()`
call sites (initial call and in-loop call) in a local `_complete(round_no)` closure that
catches `BrainError`, calls `_log_failed_call_marker(tier, round_no, exc.reason, elapsed)`
(a `logger.warning(...)` — only `.reason` is passed, never `.detail`), mutates the shared
`ReactRoundsMetrics` (`call_count`, `failed_count`, `duration_s`), then re-raises the
original exception unchanged (`raise` with no args, inside `except BrainError as exc:`).

Test `test_loop_logs_failed_marker_on_brain_error_never_leaks_detail` (test_loop.py)
forces a 500 response whose body is a secret marker string, asserts:
- `pytest.raises(BrainError)` — propagation is unchanged (Loop.run_turn still raises,
  same as before this feature; sanity-checked via `excinfo.value.detail` containing the
  secret body, confirming `.detail` really does carry the sensitive text).
- A caplog line containing `FAILED`, `tier=`, `round=1`, and the `.reason` string
  (`"backend error"`) exists.
- The secret body text (which lives only in `.detail`) never appears anywhere in the
  captured log output.

See AC-1's passing run above for this test's PASSED result. Full assertions (from
`tests/test_loop.py`):

```python
    with pytest.raises(BrainError) as excinfo:
        await loop.run_turn("s1", "t1", "hello")

    assert secret_body in excinfo.value.detail  # sanity: detail really carries it

    messages = [record.getMessage() for record in caplog.records]
    failed_lines = [m for m in messages if "FAILED" in m]
    assert failed_lines, messages
    assert "tier=" in failed_lines[0]
    assert "round=1" in failed_lines[0]
    assert "backend error" in failed_lines[0]  # BrainError.reason for a status error

    full_log = "\n".join(messages)
    assert secret_body not in full_log
```

Also exercised indirectly (nested consult path) by
`test_turn_summary_counts_failed_nested_consult_call` (test_loop_tools.py), which
asserts a `FAILED` line containing the `"unreadable response"` reason from a malformed
remote body. See AC-1's passing run above.

## AC-3: turn-level timeout (`Loop.run_turn`) and consult-level timeout (`BrainConsult.__call__`) each log a WARNING timeout marker from their existing `except asyncio.TimeoutError` handlers, without changing existing fallback behavior.

`hearth/loop.py::Loop.run_turn`'s existing `except asyncio.TimeoutError:` block now also
does `logger.warning("turn timeout tier=%s after=%.1fs", ...)` before falling through to
the unchanged `answer_text = "That took too long — here's what I have so far."` line
(untouched).

`hearth/tools/consult.py::BrainConsult.__call__`'s existing `except asyncio.TimeoutError:`
block now also does `logger.warning("consult timeout tier=%s after=%.1fs", ...)` before
the unchanged `findings = "consult_brain: that took too long, continuing without it."`
line (untouched).

Test `test_turn_timeout_logs_marker_and_counts_failed_call` (test_loop_tools.py) forces a
turn timeout via `turn_timeout_s=0.05` and a `_BlockingConsult` that sleeps 60s, and
asserts:
- `"too long" in answer` — the pre-existing fallback text assertion, unchanged from the
  prior `test_turn_timeout_emits_balanced_tool_activity` test's coverage.
- A WARNING-level record containing `"timeout"` exists.

Test `test_consult_timeout_logs_marker` (test_consult_brain.py) forces a consult timeout
via `consult_timeout_s=0.01` against a slow mock transport, and asserts:
- `isinstance(result, str)` / `result` truthy — the pre-existing degraded-findings-string
  coverage, unchanged from `test_consult_timeout_becomes_observation`.
- A WARNING-level record containing `"timeout"` exists.
- `consult.last_metrics.failed_count == 1`.

See AC-1's passing run above for both tests' PASSED results.

## AC-4: the per-turn summary counts a failed/timed-out call toward the turn's call count and total wall time, shows `(K failed)` when `K > 0`, and excludes the failed call from token/tokens-per-second totals.

`hearth/loop.py::ReactRoundsMetrics` gained a `failed_count: int = 0` field.
`Loop._log_turn_metrics` now sums `failed_count` across `own_metrics`/`nested_metrics`
and renders `calls=N` as `calls=N (K failed)` only when `K > 0` (no `(0 failed)` clutter
on the happy path — see AC-5 below).

The `ReactRoundsMetrics` object is now passed by the caller into `run_react_rounds`
(`metrics=own_metrics` in `Loop.run_turn`, `metrics=metrics` — aliased from
`self.last_metrics` — in `BrainConsult.__call__`) so that when `run_react_rounds` raises
`BrainError` mid-call, the metrics mutation already applied (failed call counted, its
elapsed time added to `duration_s`, zero tokens contributed since no `BrainResult` was
produced) is still visible to the caller after catching the exception — not lost with
the raised exception.

For a turn/consult timeout, the `except asyncio.TimeoutError:` handlers in
`Loop.run_turn` / `BrainConsult.__call__` directly increment `call_count`/`failed_count`
and add the elapsed wall time to `duration_s` on the same shared metrics object (which
may already carry any rounds that completed before cancellation, since it was mutated
in place prior to the timeout).

Test `test_turn_summary_counts_failed_nested_consult_call` (test_loop_tools.py) drives a
scenario where the orchestrator makes 2 successful local-tier calls (usage
`in=10+20=30`, `out=4+8=12`) and the nested consult's one remote-tier call raises
`BrainError` (malformed body). Asserts on the per-turn summary line:
- `"in=30" in summary` and `"out=12" in summary` — failed call contributes 0 tokens.
- `"calls=3 (1 failed)" in summary` — 2 successful + 1 failed = 3 total calls, 1 failed.

Test `test_turn_timeout_logs_marker_and_counts_failed_call` (test_loop_tools.py) asserts
`"(1 failed)" in summary_lines[-1]` for the turn-timeout scenario (1 successful round
before the blocking consult call times out, contributing the timeout as 1 more failed
call — `calls=2 (1 failed)`, confirmed via the FAILING-run assertion diff showing
`calls=0` pre-implementation vs. the post-implementation PASSED run above).

See AC-1's passing run above for both tests' PASSED results.

## AC-5: FTHR-013's happy-path per-call and per-turn tests still pass unmodified (no failure-marker logic triggers on successful calls).

Re-ran FTHR-013's existing happy-path tests, unmodified, against the finished
implementation:

```
$ /home/penguin/source/hearth/.venv/bin/python -m pytest tests/test_loop.py::test_loop_logs_per_call_and_per_turn_metrics tests/test_loop_tools.py::test_turn_summary_includes_nested_consult_metrics -v

============================= test session starts ==============================
platform linux -- Python 3.14.6, pytest-9.1.1, pluggy-1.6.0 -- /home/penguin/source/hearth/.venv/bin/python
cachedir: .pytest_cache
rootdir: /tmp/claude-1000/-home-penguin-source-hearth/f87e11cc-2fbb-4815-ae23-96a05fcf4a7b/scratchpad/FTHR-014
configfile: pyproject.toml
plugins: asyncio-1.4.0, anyio-4.14.1
asyncio: mode=Mode.AUTO, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collecting ... collected 2 items

tests/test_loop.py::test_loop_logs_per_call_and_per_turn_metrics PASSED  [ 50%]
tests/test_loop_tools.py::test_turn_summary_includes_nested_consult_metrics PASSED [100%]

============================== 2 passed in 0.02s ===============================
```

`test_turn_summary_includes_nested_consult_metrics` in particular still asserts
`"calls=4" in summary` (no ` (0 failed)` suffix) on the all-success path, confirming the
`calls_str` conditional suffix logic doesn't clutter the happy-path format.

**Full suite (no regressions anywhere in the repo):**

```
$ /home/penguin/source/hearth/.venv/bin/python -m pytest

============================== 94 passed in 0.86s ===============================
```

(94 tests total: 90 pre-existing + 4 new FTHR-014 tests, all passing.)
