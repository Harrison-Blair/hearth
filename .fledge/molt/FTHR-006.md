# FTHR-006 molt evidence

## AC-1

Tests written test-first: `tests/test_wikipedia.py` (`test_wikipedia_search_parses`
plus two supporting tests for `result_count`/`max_chars`) and
`tests/test_loop_tools.py` (`test_loop_tool_round_incorporates_observation`,
`test_tool_turn_uses_tool_tier`, `test_max_tool_rounds_cap`,
`test_toolactivity_label_only`).

Captured pre-implementation run (unimplemented `hearth/tools/wikipedia.py`, no
`registry` param on `Loop`, no tool-round logic in `hearth/loop.py`):

```
$ .venv/bin/pytest -q tests/test_wikipedia.py
==================================== ERRORS ====================================
___________________ ERROR collecting tests/test_wikipedia.py ___________________
ImportError while importing test module '.../tests/test_wikipedia.py'.
Hint: make sure your test modules/packages have valid Python names.
Traceback:
.../importlib/__init__.py:90: in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
tests/test_wikipedia.py:6: in <module>
    from hearth.tools.wikipedia import wikipedia_search
E   ModuleNotFoundError: No module named 'hearth.tools.wikipedia'
=========================== short test summary info ============================
ERROR tests/test_wikipedia.py
!!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
1 error in 0.06s

$ .venv/bin/pytest -q tests/test_loop_tools.py
FFFF                                                                     [100%]
=================================== FAILURES ===================================
________________ test_loop_tool_round_incorporates_observation _________________
...
>       loop = Loop(router, log, _Config(), registry=registry)
E       TypeError: Loop.__init__() got an unexpected keyword argument 'registry'
tests/test_loop_tools.py:103: TypeError
________________________ test_tool_turn_uses_tool_tier _________________________
...
E       TypeError: Loop.__init__() got an unexpected keyword argument 'registry'
tests/test_loop_tools.py:144: TypeError
___________________________ test_max_tool_rounds_cap ___________________________
...
E       TypeError: Loop.__init__() got an unexpected keyword argument 'registry'
tests/test_loop_tools.py:168: TypeError
_________________________ test_toolactivity_label_only _________________________
...
E       TypeError: Loop.__init__() got an unexpected keyword argument 'registry'
tests/test_loop_tools.py:200: TypeError
=========================== short test summary info ============================
FAILED tests/test_loop_tools.py::test_loop_tool_round_incorporates_observation
FAILED tests/test_loop_tools.py::test_tool_turn_uses_tool_tier - TypeError: L...
FAILED tests/test_loop_tools.py::test_max_tool_rounds_cap - TypeError: Loop._...
FAILED tests/test_loop_tools.py::test_toolactivity_label_only - TypeError: Lo...
4 failed in 0.03s
```

Both files fail for the expected reason: `hearth/tools/wikipedia.py` does not
exist yet, and `Loop` does not yet accept a `registry` or implement tool rounds.

Post-implementation run, all green, plus the full suite (no regressions):

```
$ .venv/bin/pytest -q tests/test_wikipedia.py tests/test_loop_tools.py -v
tests/test_wikipedia.py ...                                              [ 42%]
tests/test_loop_tools.py ....                                            [100%]
7 passed in 0.03s

$ .venv/bin/pytest -q
.............................                                            [100%]
29 passed in 0.09s

$ .venv/bin/ruff check .
All checks passed!
```

## AC-2

`hearth/tools/registry.py`'s `ToolRegistry` keeps the FTHR-002 seam shape
(`specs()` / `dispatch()`) unchanged, now backed by exactly one tool
(`wikipedia_search`, module-level `SPEC` in `hearth/tools/wikipedia.py`).
`specs()` returns `[]` when no config/client is wired (preserves the empty
seam's original no-op behavior for callers that don't opt in — e.g. `Loop`'s
default `registry=None` path) or when `wikipedia_enabled` is false, and
`[wikipedia.SPEC]` otherwise — always at most the one tool, admitting future
tools unchanged (add a spec + a name check in `dispatch`).

`wikipedia_search` is tested hermetically via `httpx.MockTransport` in
`tests/test_wikipedia.py`:

```
$ .venv/bin/pytest -q tests/test_wikipedia.py -v
tests/test_wikipedia.py::test_wikipedia_search_parses PASSED
tests/test_wikipedia.py::test_wikipedia_search_respects_result_count PASSED
tests/test_wikipedia.py::test_wikipedia_search_respects_max_chars PASSED
3 passed in 0.01s
```

`test_wikipedia_search_parses` asserts the canned REST body is turned into a
summary containing the expected title/excerpt text and that the request hit
the configured `endpoint` with the query. The other two pin `result_count`
(truncates to N pages) and `max_chars` (truncates the joined string length).

## AC-3

`hearth/loop.py`'s `Loop.run_turn` now computes
`tools_available = bool(tool_specs) and config.agent.tool_mode != "off"` and
calls `router.select(tools_available=tools_available)`, passing `tools=`
through to `selection.brain.complete`. When the brain returns tool calls, the
loop dispatches through `self._registry.dispatch(...)`, appends the
observation as a `tool` message, and re-queries the brain — the final answer
reflects the observation.

```
$ .venv/bin/pytest -q tests/test_loop_tools.py::test_tool_turn_uses_tool_tier tests/test_loop_tools.py::test_loop_tool_round_incorporates_observation -v
tests/test_loop_tools.py::test_tool_turn_uses_tool_tier PASSED
tests/test_loop_tools.py::test_loop_tool_round_incorporates_observation PASSED
2 passed in 0.01s
```

`test_tool_turn_uses_tool_tier` asserts the routing_decision event's `tier`
is `"tool"` and that the first outbound request carried the `wikipedia_search`
tool spec. `test_loop_tool_round_incorporates_observation` scripts a backend
that returns a `tool_call` then a final answer referencing the stubbed
observation text, and asserts the returned `answer` is exactly that text.

## AC-4

`hearth/loop.py` logs `tool_call` (name + arguments) and `observation` (name +
result) events per dispatch via the existing `EventLog`, and emits
`ToolActivity(turn_id, "start"|"end", label)` through `emit` around each
dispatch — `ToolActivity` (frozen shape from FTHR-003, `hearth/events.py`) only
ever carries `turn_id`/`phase`/`label`, so there is no field to leak
query/arguments/observation content through even by accident; the veneer's
`serialize` (`hearth/veneer/protocol.py`) further whitelists just
`phase`/`label` onto the wire.

```
$ .venv/bin/pytest -q tests/test_loop_tools.py::test_toolactivity_label_only tests/test_loop_tools.py::test_loop_tool_round_incorporates_observation -v
tests/test_loop_tools.py::test_toolactivity_label_only PASSED
tests/test_loop_tools.py::test_loop_tool_round_incorporates_observation PASSED
2 passed in 0.01s
```

`test_toolactivity_label_only` scripts a tool call/observation containing the
literal substring "secret" and asserts every emitted `ToolActivity` has field
set `{"turn_id", "phase", "label"}`, `label == "search"` (the coarse label,
never the query), and no "secret" text anywhere on the emitted event.
`test_loop_tool_round_incorporates_observation` additionally asserts the
`tool_call`/`observation` events logged to the `EventLog` (a separate,
appropriate channel) do carry the full name/arguments/result.

## AC-5

`Loop._run_tool_rounds`'s `while result.tool_calls and round_count <
config.agent.max_tool_rounds` caps dispatch rounds; once the cap is hit, the
loop exits and `run_turn` still returns a final answer (falling back to an
explicit string if the capped-out result carries no text).

```
$ .venv/bin/pytest -q tests/test_loop_tools.py::test_max_tool_rounds_cap -v
tests/test_loop_tools.py::test_max_tool_rounds_cap PASSED
1 passed in 0.00s
```

`test_max_tool_rounds_cap` scripts a backend that always returns a tool call
(never a bare final answer), sets `max_tool_rounds=2`, and asserts exactly 2
`tool_call` events were logged (not 3+) and that `run_turn` still returns a
non-empty string answer rather than hanging or raising.

## Config/schema note (pre-approved deviation)

The feather spec's Approach section references `config.tool.wikipedia.{endpoint,
result_count, max_chars, lang, timeout}` as a nested config object. The actual
`ToolConfig` in `hearth/config.py` (from FTHR-001) only has flat fields:
`wikipedia_enabled: bool`, `wikipedia_language: str`. There is no nested
`wikipedia` sub-object. Per the orchestrator's pre-approval (spawn prompt),
this was resolved by extending `ToolConfig` with additional **flat** fields
matching the existing naming convention: `wikipedia_endpoint: str`,
`wikipedia_result_count: int`, `wikipedia_max_chars: int`,
`wikipedia_timeout: float` — reusing the existing `wikipedia_language` field for
`lang` (no duplicate added). Matching entries were added to both `config.yaml`
and `default-config.yaml` (with an inline comment per field in the latter, per
the two-file convention). This is in scope for this feather: the Approach
section requires these config values to exist for `wikipedia_search`'s
configuration, so the minimal schema extension is necessary, not scope creep.
