# FTHR-013 molt evidence: Per-call and per-turn metrics capture

All commands run inside the worktree
`/tmp/claude-1000/-home-penguin-source-hearth/f87e11cc-2fbb-4815-ae23-96a05fcf4a7b/scratchpad/FTHR-013`
on branch `feather/FTHR-013-metrics-capture`.

**Important pytest invocation note:** this worktree shares the repo's single
`.venv` (an editable install recorded against the main repo's absolute path).
Invoking the `pytest` console-script directly resolves `import hearth` to the
*main repo's* copy, not this worktree's, because the script's own directory
(not cwd) lands in `sys.path[0]`. `python -m pytest` does insert cwd first, so
it correctly picks up this worktree's `hearth/`. All post-implementation runs
below use `.venv/bin/python -m pytest` for that reason. The one pre-implementation
run below used the bare `pytest` script, but since `hearth/` was byte-for-byte
identical between the worktree and main repo at that point (no edits made yet),
the failures it captured are equally valid evidence of the pre-implementation
behavior.

## AC-1: tests observed failing before implementation, passing after

### Pre-implementation (unchanged code): FAILING for the expected reason

Command: `.venv/bin/pytest tests/test_local_backend.py tests/test_remote_backend.py tests/test_loop.py tests/test_loop_tools.py tests/test_consult_brain.py tests/test_veneer.py -q`

```
....FFFF..F..F.....F..........                                           [100%]
=================================== FAILURES ===================================
_________________ test_local_backend_captures_usage_and_model __________________
...
        result = await backend.complete([Message(role="user", content="hi")], tools=None)

>       assert result.model == backend_config.model
               ^^^^^^^^^^^^
E       AttributeError: 'BrainResult' object has no attribute 'model'

tests/test_local_backend.py:140: AttributeError
_________________ test_local_backend_captures_reasoning_tokens _________________
...
>       assert result.reasoning_tokens == 3
               ^^^^^^^^^^^^^^^^^^^^^^^
E       AttributeError: 'BrainResult' object has no attribute 'reasoning_tokens'

tests/test_local_backend.py:173: AttributeError
______________ test_local_backend_missing_usage_defaults_to_none _______________
...
>       assert result.prompt_tokens is None
               ^^^^^^^^^^^^^^^^^^^^
E       AttributeError: 'BrainResult' object has no attribute 'prompt_tokens'

tests/test_local_backend.py:194: AttributeError
________________ test_local_backend_duration_is_positive_float _________________
...
>       assert result.duration_s is not None
               ^^^^^^^^^^^^^^^^^
E       AttributeError: 'BrainResult' object has no attribute 'duration_s'

tests/test_local_backend.py:217: AttributeError
_________________ test_remote_backend_captures_usage_and_model _________________
...
>       assert result.model == "openrouter/free"
               ^^^^^^^^^^^^
E       AttributeError: 'BrainResult' object has no attribute 'model'

tests/test_remote_backend.py:74: AttributeError
_________________ test_loop_logs_per_call_and_per_turn_metrics _________________
...
        call_lines = [m for m in messages if "round=1" in m and "tier=" in m]
>       assert call_lines, messages
E       AssertionError: ['HTTP Request: POST http://localhost:11434/v1/chat/completions "HTTP/1.1 200 OK"']
E       assert []

tests/test_loop.py:127: AssertionError
------------------------------ Captured log call -------------------------------
INFO     httpx:_client.py:1740 HTTP Request: POST http://localhost:11434/v1/chat/completions "HTTP/1.1 200 OK"
______________ test_turn_summary_includes_nested_consult_metrics _______________
...
        messages = [record.getMessage() for record in caplog.records]
        summary_lines = [m for m in messages if "turn=1" in m]
>       assert summary_lines, messages
E       AssertionError: ['HTTP Request: POST http://local-llm.test/v1/chat/completions "HTTP/1.1 200 OK"', 'HTTP Request: POST https://remote-.../chat/completions "HTTP/1.1 200 OK"', 'HTTP Request: POST http://local-llm.test/v1/chat/completions "HTTP/1.1 200 OK"']
E       assert []

tests/test_loop_tools.py:302: AssertionError
------------------------------ Captured log call -------------------------------
INFO     httpx:_client.py:1740 HTTP Request: POST http://local-llm.test/v1/chat/completions "HTTP/1.1 200 OK"
INFO     httpx:_client.py:1740 HTTP Request: POST https://remote-llm.test/v1/chat/completions "HTTP/1.1 200 OK"
INFO     httpx:_client.py:1740 HTTP Request: POST https://remote-llm.test/v1/chat/completions "HTTP/1.1 200 OK"
INFO     httpx:_client.py:1740 HTTP Request: POST http://local-llm.test/v1/chat/completions "HTTP/1.1 200 OK"
=========================== short test summary info ============================
FAILED tests/test_local_backend.py::test_local_backend_captures_usage_and_model
FAILED tests/test_local_backend.py::test_local_backend_captures_reasoning_tokens
FAILED tests/test_local_backend.py::test_local_backend_missing_usage_defaults_to_none
FAILED tests/test_local_backend.py::test_local_backend_duration_is_positive_float
FAILED tests/test_remote_backend.py::test_remote_backend_captures_usage_and_model
FAILED tests/test_loop.py::test_loop_logs_per_call_and_per_turn_metrics - Ass...
FAILED tests/test_loop_tools.py::test_turn_summary_includes_nested_consult_metrics
7 failed, 23 passed in 0.19s
```

Each of the 7 new/extended tests failed for the expected reason: the new
`BrainResult` fields don't exist yet (`AttributeError`), and no per-call/
per-turn metrics log lines are emitted yet (only httpx's own request-logging
line is captured, so the `round=`/`turn=` substring assertions find nothing).
The other 23 tests (pre-existing, untouched) still pass, confirming the new
tests are additive.

### Post-implementation: full suite passing

Command: `.venv/bin/python -m pytest -q`

```
........................................................................ [ 85%]
............                                                             [100%]
84 passed in 0.79s
```

77 pre-existing tests + 7 new/extended tests (4 in `test_local_backend.py`, 1
in `test_remote_backend.py`, 1 in `test_loop.py`, 1 in `test_loop_tools.py`) =
84, all green.

## AC-2: `BrainResult` carries the new metrics fields, identically via both backends

Command: `.venv/bin/python -m pytest tests/test_local_backend.py tests/test_remote_backend.py -v`

```
tests/test_local_backend.py::test_local_backend_parses_completion PASSED [  9%]
tests/test_local_backend.py::test_local_backend_still_parses PASSED      [ 18%]
tests/test_local_backend.py::test_retries_transient_connection_error PASSED [ 27%]
tests/test_local_backend.py::test_no_retry_exhausts_and_raises PASSED    [ 36%]
tests/test_local_backend.py::test_local_backend_captures_usage_and_model PASSED [ 45%]
tests/test_local_backend.py::test_local_backend_captures_reasoning_tokens PASSED [ 54%]
tests/test_local_backend.py::test_local_backend_missing_usage_defaults_to_none PASSED [ 63%]
tests/test_local_backend.py::test_local_backend_duration_is_positive_float PASSED [ 72%]
tests/test_local_backend.py::test_timeout_is_not_retried PASSED          [ 81%]
tests/test_remote_backend.py::test_remote_backend_auth_and_parse PASSED  [ 90%]
tests/test_remote_backend.py::test_remote_backend_captures_usage_and_model PASSED [100%]

============================== 11 passed in 0.02s ==============================
```

`test_local_backend_captures_usage_and_model` asserts `model`, `prompt_tokens`,
`completion_tokens`, `total_tokens` are populated and `reasoning_tokens is None`
when absent. `test_local_backend_captures_reasoning_tokens` asserts
`completion_tokens_details.reasoning_tokens` maps to `reasoning_tokens`.
`test_local_backend_missing_usage_defaults_to_none` asserts every numeric field
is `None` (never `0`) when the `usage` key is absent entirely, and that
`complete()` doesn't raise. `test_local_backend_duration_is_positive_float`
asserts `duration_s` is populated regardless of `usage` presence.
`test_remote_backend_captures_usage_and_model` repeats the usage/model
assertions through `RemoteBackend`, proving both backends get identical
capture via the shared `_OpenAICompatBackend.complete()` (implementation:
`hearth/brain/openai_compat.py` — `usage = body.get("usage") or {}`, mapping
each key with `.get(...)` so absent keys yield `None`, never a fabricated `0`).

## AC-3: per-call INFO log line

Command: `.venv/bin/python -m pytest tests/test_loop.py -v`

```
tests/test_loop.py::test_loop_single_turn_logs_and_answers PASSED        [ 25%]
tests/test_loop.py::test_loop_multi_turn_reconstructs_history PASSED     [ 50%]
tests/test_loop.py::test_loop_logs_per_call_and_per_turn_metrics PASSED  [ 75%]
tests/test_loop.py::test_persona_restyle_noop PASSED                     [100%]

============================== 4 passed in 0.02s ===============================
```

`test_loop_logs_per_call_and_per_turn_metrics` asserts (via `caplog`) that a
single-round turn logs one line containing `round=1` and `tier=`, and that the
same line contains `in=`, `out=`, and `thinking=n/a` (the canned response has
no reasoning tokens). Implementation: `hearth/loop.py::_log_call_metrics`,
called from `run_react_rounds`'s new `_record` closure after every
`brain.complete()` — the initial call is logged as `round=1`; each subsequent
loop iteration is logged as `round=<round_count + 1>`.

## AC-4: per-turn INFO summary line, including nested consult_brain metrics

Command: `.venv/bin/python -m pytest tests/test_loop.py tests/test_loop_tools.py tests/test_consult_brain.py -v`

```
tests/test_loop.py::test_loop_single_turn_logs_and_answers PASSED        [  6%]
tests/test_loop.py::test_loop_multi_turn_reconstructs_history PASSED     [ 13%]
tests/test_loop.py::test_loop_logs_per_call_and_per_turn_metrics PASSED  [ 20%]
tests/test_loop.py::test_persona_restyle_noop PASSED                     [ 26%]
tests/test_loop_tools.py::test_orchestrator_first_request_offers_consult_brain_at_default_tier PASSED [ 33%]
tests/test_loop_tools.py::test_consult_dispatches_nested_wikipedia_search PASSED [ 40%]
tests/test_loop_tools.py::test_wikipedia_search_never_offered_at_top_level PASSED [ 46%]
tests/test_loop_tools.py::test_nested_tool_round_cap PASSED              [ 53%]
tests/test_loop_tools.py::test_turn_summary_includes_nested_consult_metrics PASSED [ 60%]
tests/test_loop_tools.py::test_concurrent_turns_keep_their_own_consult_context PASSED [ 66%]
tests/test_loop_tools.py::test_turn_timeout_emits_balanced_tool_activity PASSED [ 73%]
tests/test_consult_brain.py::test_consult_runs_nested_react_over_wikipedia PASSED [ 80%]
tests/test_consult_brain.py::test_consult_brain_error_becomes_observation PASSED [ 86%]
tests/test_consult_brain.py::test_consult_timeout_becomes_observation PASSED [ 93%]
tests/test_consult_brain.py::test_consult_timeout_emits_balanced_tool_activity PASSED [100%]

============================== 15 passed in 0.16s ==============================
```

`test_loop_logs_per_call_and_per_turn_metrics` (`test_loop.py`) asserts a
`turn=1` summary line is emitted on the first turn in a session, and `turn=2`
on the second turn in the same session (session-sequential turn number,
computed by counting prior `final_answer` events).

`test_turn_summary_includes_nested_consult_metrics` (`test_loop_tools.py`)
drives a turn where `consult_brain` fires a nested ReAct round on the `tool`
tier over `wikipedia_search`, with distinct `usage` values on every one of the
4 underlying LLM calls (2 orchestrator, 2 nested). It asserts the `turn=1`
summary line contains `in=41` (10+20 orchestrator + 5+6 nested),
`out=17` (4+8 orchestrator + 3+2 nested), and `calls=4` (all four calls
counted, not just the orchestrator's two) — proving the per-turn totals
correctly include nested `consult_brain` metrics.

Implementation: `hearth/tools/consult.py::BrainConsult` now exposes
`self.last_metrics` (a `ReactRoundsMetrics`, reset to zero at the start of
every `__call__` and set from `run_react_rounds`'s result on success) as a
side attribute — `__call__`'s return type (`str`) is unchanged for the tool
`dispatch` protocol. `hearth/loop.py::Loop.run_turn`'s `consult_dispatch`
closure appends `getattr(self._consult, "last_metrics", None) or
ReactRoundsMetrics()` to a per-turn `nested_metrics` list after each
`consult_brain` dispatch (the `getattr` fallback keeps `test_loop_tools.py`'s
pre-existing `_RecordingConsult`/`_BlockingConsult` test doubles — which don't
set `last_metrics` — working unchanged). `Loop._log_turn_metrics` sums the
orchestrator's own metrics with every entry in `nested_metrics` and logs one
INFO line with the turn number, total rounds, total calls, total in/out
tokens, total duration, and blended tok/s.

## AC-5: INFO-level, no new config, wire whitelist unaffected

Command: `.venv/bin/python -m pytest tests/test_veneer.py -v`

```
tests/test_veneer.py::test_veneer_roundtrip PASSED                       [ 25%]
tests/test_veneer.py::test_no_tool_internals_cross_boundary PASSED       [ 50%]
tests/test_veneer.py::test_loop_error_maps_to_error_message PASSED       [ 75%]
tests/test_veneer.py::test_malformed_frame_rejected_connection_survives PASSED [100%]

============================== 4 passed in 0.02s ===============================
```

`test_no_tool_internals_cross_boundary` re-asserts the `forbidden_keys`
whitelist (`query`, `arguments`, `observation`, `result` never cross the
wire) unmodified and still passes — no metrics field was added anywhere near
`hearth/veneer/protocol.py::serialize`. All new logging in this feather is via
`logger.info(...)` on the module's existing loggers (`hearth.loop`,
`hearth.tools.consult`) — no new `LoggingConfig` field, no new config section.
Also confirmed by `test_logging.py::test_logging_failure_does_not_crash_turn`
(pre-existing, in the full suite run below) — the new per-call logging in
`run_react_rounds` is wrapped in its own `try/except Exception: pass` so a
logging failure still can't crash a turn.

Full-suite regression run: `.venv/bin/python -m pytest -q`

```
........................................................................ [ 85%]
............                                                             [100%]
84 passed in 0.79s
```

`ruff check hearth/` — all checks passed (no lint regressions introduced).
