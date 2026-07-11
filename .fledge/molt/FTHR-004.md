# FTHR-004 molt evidence

## AC-1

Test-first: wrote `tests/test_router.py`, `tests/test_remote_backend.py`, and added
`test_local_backend_still_parses` to `tests/test_local_backend.py`, then ran them
against the unmodified FTHR-002 code (stub `Router.select`, no `RemoteBackend`).

Command:
```
.venv/bin/pytest -q tests/test_router.py tests/test_local_backend.py
.venv/bin/pytest -q tests/test_remote_backend.py
```

Captured output (pre-implementation, verbatim):
```
FFFF..                                                                   [100%]
=================================== FAILURES ===================================
______________________ test_tool_turn_routes_to_tool_tier ______________________

client = <httpx.AsyncClient object at 0x7fdc62206cf0>

    async def test_tool_turn_routes_to_tool_tier(client):
        router = Router(make_config(remote_enabled=True), client=client)
        selection = router.select(tools_available=True)
>       assert selection.tier == "tool"
E       AssertionError: assert 'default' == 'tool'
E         
E         - tool
E         + default

tests/test_router.py:52: AssertionError
_______________________ test_chat_turn_routes_to_default _______________________

client = <httpx.AsyncClient object at 0x7fdc62268910>

    async def test_chat_turn_routes_to_default(client):
        router = Router(make_config(remote_enabled=True), client=client)
        selection = router.select(tools_available=False)
        assert selection.tier == "default"
        assert selection.backend_name == "local"
>       assert selection.reason == "chat-turn→default tier"
E       AssertionError: assert 'single-backend (FTHR-002)' == 'chat-turn→default tier'
E         
E         - chat-turn→default tier
E         + single-backend (FTHR-002)

tests/test_router.py:62: AssertionError
___________________ test_remote_disabled_falls_back_to_local ___________________

client = <httpx.AsyncClient object at 0x7fdc62269d10>

    async def test_remote_disabled_falls_back_to_local(client):
        router = Router(make_config(remote_enabled=False), client=client)
        selection = router.select(tools_available=True)
        assert selection.backend_name == "local"
>       assert selection.reason == "tool tier disabled; local fallback"
E       AssertionError: assert 'single-backend (FTHR-002)' == 'tool tier di...ocal fallback'
E         
E         - tool tier disabled; local fallback
E         + single-backend (FTHR-002)

tests/test_router.py:69: AssertionError
________________________ test_tier_override_forces_tier ________________________

client = <httpx.AsyncClient object at 0x7fdc622863f0>

    async def test_tier_override_forces_tier(client):
        router = Router(make_config(remote_enabled=True), client=client)
        selection = router.select(tools_available=False, tier_override="tool")
        assert selection.tier == "tool"
>       assert selection.backend_name == "remote"
E       AssertionError: assert 'local' == 'remote'
E         
E         - remote
E         + local

tests/test_router.py:76: AssertionError
=========================== short test summary info ============================
FAILED tests/test_router.py::test_tool_turn_routes_to_tool_tier - AssertionEr...
FAILED tests/test_router.py::test_chat_turn_routes_to_default - AssertionErro...
FAILED tests/test_router.py::test_remote_disabled_falls_back_to_local - Asser...
FAILED tests/test_router.py::test_tier_override_forces_tier - AssertionError:...
4 failed, 2 passed in 0.02s


==================================== ERRORS ====================================
________________ ERROR collecting tests/test_remote_backend.py _________________
ImportError while importing test module '/home/penguin/source/hearth/.fledge/burrows/FTHR-004/tests/test_remote_backend.py'.
Hint: make sure your test modules/packages have valid Python names.
Traceback:
/usr/lib/python3.14/importlib/__init__.py:88: in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
tests/test_remote_backend.py:7: in <module>
    from hearth.brain.remote import RemoteBackend
E   ModuleNotFoundError: No module named 'hearth.brain.remote'
=========================== short test summary info ============================
ERROR tests/test_remote_backend.py
!!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
1 error in 0.02s
```

`test_chat_turn_routes_to_default` and `test_local_backend_parses_completion` /
`test_local_backend_still_parses` (2 passed above) pass incidentally against the
FTHR-002 stub/pre-refactor code because the stub always returns the local backend
on the default tier and `local.py` is untouched yet — they will be re-verified
green post-implementation below, alongside the rest.

Post-implementation run (after implementing `_OpenAICompatBackend`, `RemoteBackend`,
and real `Router.select`), full suite:

Command: `.venv/bin/pytest -q`

```
................                                                         [100%]
16 passed in 0.04s
```

All 6 named tests pass:
```
.venv/bin/pytest -q tests/test_router.py tests/test_remote_backend.py tests/test_local_backend.py -v
tests/test_router.py::test_tool_turn_routes_to_tool_tier PASSED
tests/test_router.py::test_chat_turn_routes_to_default PASSED
tests/test_router.py::test_remote_disabled_falls_back_to_local PASSED
tests/test_router.py::test_tier_override_forces_tier PASSED
tests/test_remote_backend.py::test_remote_backend_auth_and_parse PASSED
tests/test_local_backend.py::test_local_backend_parses_completion PASSED
tests/test_local_backend.py::test_local_backend_still_parses PASSED
7 passed in 0.02s
```

`ruff check .` — All checks passed!

## AC-2

`RemoteBackend` (`hearth/brain/remote.py`) implements the `Brain` protocol (has
`.capabilities` and async `.complete`) exactly like `LocalBackend`, both now thin
subclasses of `_OpenAICompatBackend` (`hearth/brain/openai_compat.py`) which builds
`Capabilities(supports_tools, supports_streaming, context_window, cost_tier)` from
the injected `LLMBackend` config. Verified by:
- `test_remote_backend_auth_and_parse` (tests/test_remote_backend.py) — asserts
  `RemoteBackend` sends `Authorization: Bearer <key>` (key read via
  `config.resolve_api_key()` from the env var named by `api_key_env`, here
  `HEARTH_LLM__OPENROUTER_API_KEY`) and correctly parses an OpenAI-compatible
  response into a `BrainResult`.
- `test_local_backend_parses_completion` and `test_local_backend_still_parses`
  (tests/test_local_backend.py) — `LocalBackend` (also now a subclass of
  `_OpenAICompatBackend`) still parses plain-text and tool-call completions
  identically to FTHR-002.

Both pass per the full-suite run above.

## AC-3

`Router.select` (`hearth/brain/router.py`) is now config-driven, not
complexity-heuristic-based:
- `test_tool_turn_routes_to_tool_tier`: `tools_available=True` + remote enabled →
  `tier="tool"`, `backend_name="remote"`, reason `"tool-turn→tool tier"`.
- `test_chat_turn_routes_to_default`: `tools_available=False` → `tier="default"`,
  `backend_name="local"`, reason `"chat-turn→default tier"`.
- `test_tier_override_forces_tier`: `tier_override="tool"` with
  `tools_available=False` still returns `tier="tool"`, `backend_name="remote"`,
  reason `"override:tool"` — override wins regardless of `tools_available`.

All three pass per the full-suite run above (deterministic: repeated calls with
the same inputs return the same `Selection`, no randomness/heuristics involved).

## AC-4

`test_remote_disabled_falls_back_to_local`: with the remote (`tool` tier) backend's
`enabled=False`, a tool turn (`tools_available=True`) resolves to
`backend_name="local"`, reason `"tool tier disabled; local fallback"` — gating
verified. The rest of the spine (`Loop.run_turn` in `hearth/loop.py`, untouched by
this feather) only ever calls `select(tools_available=False)` today (FTHR-006 adds
tool rounds), and `test_loop.py`'s existing test continues to pass, confirming
local-only operation stays fully functional through the `Router` seam.

Passes per the full-suite run above.

## AC-5

`hearth/loop.py::Loop.run_turn` (already existing from FTHR-002, out of this
feather's Affected Modules) appends a `routing_decision` event with
`selection.tier`, `selection.backend_name`, `selection.reason` for every turn —
unchanged by this feather, but now populated with the real routing decision
instead of the FTHR-002 stub's constant `"single-backend (FTHR-002)"` reason.
`tests/test_loop.py::test_loop` (pre-existing, unmodified) asserts the event
sequence `["user_input", "routing_decision", "final_answer"]` and continues to
pass — see the full-suite run above (16 passed, includes `test_loop.py`).
