# FTHR-002 molt evidence

Worktree: `.fledge/burrows/FTHR-002`, branch `feather/FTHR-002-core-spine-in-process-tracer`.
Venv: `python3 -m venv .venv && .venv/bin/pip install -e '.[dev,llm]'`.

## AC-1

Tests listed in the feather's Tests section were written first (`tests/test_local_backend.py`,
`tests/test_event_log.py`, `tests/test_loop.py`, `tests/conftest.py`), then run against the
unimplemented code (only `hearth/brain/__init__.py`, `hearth/tools/__init__.py`,
`hearth/memory/__init__.py` existed — no `base.py`/`local.py`/`router.py`/`log.py`/`persona.py`/
`loop.py`/`events.py`). Command:

```
.venv/bin/pytest tests/test_local_backend.py tests/test_event_log.py tests/test_loop.py -v
```

Captured FAILING output (collection errors — the modules under test don't exist yet):

```
============================= test session starts ==============================
platform linux -- Python 3.14.6, pytest-9.1.1, pluggy-1.6.0 -- /home/penguin/source/hearth/.fledge/burrows/FTHR-002/.venv/bin/python3
cachedir: .pytest_cache
rootdir: /home/penguin/source/hearth/.fledge/burrows/FTHR-002
configfile: pyproject.toml
plugins: asyncio-1.4.0, anyio-4.14.1
asyncio: mode=Mode.AUTO, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collecting ... collected 0 items / 3 errors

==================================== ERRORS ====================================
_________________ ERROR collecting tests/test_local_backend.py _________________
ImportError while importing test module '/home/penguin/source/hearth/.fledge/burrows/FTHR-002/tests/test_local_backend.py'.
Hint: make sure your test modules/packages have valid Python names.
Traceback:
/usr/lib/python3.14/importlib/__init__.py:88: in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
tests/test_local_backend.py:6: in <module>
    from hearth.brain.base import Message
E   ModuleNotFoundError: No module named 'hearth.brain.base'
___________________ ERROR collecting tests/test_event_log.py ___________________
ImportError while importing test module '/home/penguin/source/hearth/.fledge/burrows/FTHR-002/tests/test_event_log.py'.
Hint: make sure your test modules/packages have valid Python names.
Traceback:
/usr/lib/python3.14/importlib/__init__.py:88: in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
tests/test_event_log.py:4: in <module>
    from hearth.memory.log import EventLog
E   ModuleNotFoundError: No module named 'hearth.memory.log'
_____________________ ERROR collecting tests/test_loop.py ______________________
ImportError while importing test module '/home/penguin/source/hearth/.fledge/burrows/FTHR-002/tests/test_loop.py'.
Hint: make sure your test modules/packages have valid Python names.
Traceback:
/usr/lib/python3.14/importlib/__init__.py:88: in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
tests/test_loop.py:8: in <module>
    from hearth.brain.router import Router
E   ModuleNotFoundError: No module named 'hearth.brain.router'
=========================== short test summary info ============================
ERROR tests/test_local_backend.py
ERROR tests/test_event_log.py
ERROR tests/test_loop.py
!!!!!!!!!!!!!!!!!!! Interrupted: 3 errors during collection !!!!!!!!!!!!!!!!!!!!
============================== 3 errors in 0.06s ===============================
```

After implementing `hearth/brain/base.py`, `hearth/brain/local.py`, `hearth/brain/router.py`,
`hearth/events.py`, `hearth/tools/registry.py`, `hearth/memory/log.py`, `hearth/persona.py`,
`hearth/loop.py`, the full suite (pre-existing FTHR-001 tests + the new tests) passes:

```
$ .venv/bin/pytest -v
============================= test session starts ==============================
platform linux -- Python 3.14.6, pytest-9.1.1, pluggy-1.6.0 -- /home/penguin/source/hearth/.fledge/burrows/FTHR-002/.venv/bin/python3
cachedir: .pytest_cache
rootdir: /home/penguin/source/hearth/.fledge/burrows/FTHR-002
configfile: pyproject.toml
plugins: asyncio-1.4.0, anyio-4.14.1
asyncio: mode=Mode.AUTO, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collecting ... collected 10 items

tests/test_app.py::test_version_command PASSED                           [ 10%]
tests/test_config.py::test_config_loads_yaml_base PASSED                 [ 20%]
tests/test_config.py::test_env_overrides_yaml PASSED                     [ 30%]
tests/test_config.py::test_secret_from_env_only PASSED                   [ 40%]
tests/test_config.py::test_tier_roles_resolve PASSED                     [ 50%]
tests/test_event_log.py::test_event_log_append_and_read PASSED           [ 60%]
tests/test_local_backend.py::test_local_backend_parses_completion PASSED [ 70%]
tests/test_loop.py::test_loop_single_turn_logs_and_answers PASSED        [ 80%]
tests/test_loop.py::test_loop_multi_turn_reconstructs_history PASSED     [ 90%]
tests/test_loop.py::test_persona_restyle_noop PASSED                     [100%]

============================== 10 passed in 0.04s ==============================
```

`ruff check .` also passes clean (`All checks passed!`).

## AC-2

`hearth/brain/base.py` defines `Brain` as a `runtime_checkable` `Protocol` with `capabilities:
Capabilities` and `async def complete(self, messages, tools) -> BrainResult`.
`hearth/brain/local.py`'s `LocalBackend` implements it: builds an OpenAI-compatible
`/chat/completions` request from a `hearth.config.LLMBackend` (base_url/model/api_key_env/etc),
POSTs via an injected `httpx.AsyncClient`, and parses `choices[0].message` into a `BrainResult`
(`text`, `tool_calls`, `finish_reason`, `backend`, `tier`).

Evidence: `tests/test_local_backend.py::test_local_backend_parses_completion` — a `MockTransport`
returns a canned OpenAI-compatible body; asserts `result.text == "hi there"`,
`result.tool_calls == []`, `result.finish_reason == "stop"`, `result.backend == "local"`,
`result.tier == "default"`, and that the request hit `/chat/completions` (no real network call).
Passing run: see the `pytest -v` output above (`test_local_backend.py::test_local_backend_parses_completion PASSED`).

## AC-3

`hearth/memory/log.py`'s `EventLog` creates the SQLite `events` table exactly as specified
(`id INTEGER PRIMARY KEY AUTOINCREMENT, session_id, turn_id, ts_utc, type, provenance,
payload_json`), exposes only `append(...)` and `read_session(...)` — no update/delete method
exists on the class.

Evidence: `tests/test_event_log.py::test_event_log_append_and_read` — appends two events to
session `s1` and one to session `s2`; asserts `read_session("s1")` returns exactly the two `s1`
events in `id` order with their original `type`/`payload`, and asserts
`not hasattr(log, "update")` / `not hasattr(log, "delete")`. Passing run: see `pytest -v` above
(`test_event_log.py::test_event_log_append_and_read PASSED`).

## AC-4

`hearth/loop.py`'s `Loop.run_turn` appends `user_input`, calls `Router.select(tools_available=False)`
(returning a `Selection`), appends `routing_decision` with `tier`/`backend_name`/`reason`, calls
`sel.brain.complete(messages, tools=None)`, then appends `final_answer`, and returns the answer.
`emit: EventSink = null_sink` is accepted as a parameter (wired for FTHR-006's `ToolActivity`
emission) though unused in this feather's body.

Evidence: `tests/test_loop.py::test_loop_single_turn_logs_and_answers` — asserts
`await loop.run_turn("s1", "t1", "hello") == "answer one"` (the backend's canned text) and that
`log.read_session("s1")` shows event types in order `["user_input", "routing_decision",
"final_answer"]`, with the `routing_decision` payload carrying `backend_name == "local"` and
`tier == "default"` from the `Selection` `Router.select` returned. Passing run: see `pytest -v`
above (`test_loop.py::test_loop_single_turn_logs_and_answers PASSED`).

## AC-5

`Loop.run_turn` reconstructs history by reading the session's `user_input`/`final_answer` events
back from `EventLog.read_session` (no separate history store) and bounds the reconstructed
window to the last `max_history_turns` exchanges (2 events each) plus the just-appended current
`user_input`.

Evidence: `tests/test_loop.py::test_loop_multi_turn_reconstructs_history` — runs three turns on
the same session with `conversation.max_history_turns = 1` and inspects the actual JSON bodies
sent to the (mocked) backend:
- Turn 2's request messages are `["first message", "answer 1", "second message"]` — the first
  exchange is present (there was only one prior turn, within the bound).
- Turn 3's request messages are `["second message", "answer 2", "third message"]` —
  `"first message"` is explicitly asserted absent, proving the window is bounded by
  `max_history_turns` rather than including the full log.

Passing run: see `pytest -v` above
(`test_loop.py::test_loop_multi_turn_reconstructs_history PASSED`).

## AC-6

`hearth/persona.py`'s `restyle(text, ctx=None)` is an async no-op returning `text` unchanged.
`Loop.run_turn` calls it only once, at the tail, on `result.text` (the final answer), before the
`final_answer` log append.

Evidence: `tests/test_loop.py::test_persona_restyle_noop` — asserts
`await restyle("verbatim text", ctx=None) == "verbatim text"`. Additionally,
`test_loop_single_turn_logs_and_answers`'s assertion that `run_turn`'s return value equals the
backend's raw canned text (`"answer one"`) demonstrates the no-op passes the loop's output through
unchanged. Passing run: see `pytest -v` above (both tests `PASSED`).
