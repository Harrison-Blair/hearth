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

(Post-implementation passing run appended below once implementation lands.)

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
