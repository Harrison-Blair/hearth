# FTHR-010 molt evidence: Remote brain guard prompt

## AC-1
Tests observed failing before implementation, and passing after.

### Pre-implementation (failing)

Command: `.venv/bin/python -m pytest tests/test_brain_guard.py -v`

```
============================= test session starts ==============================
platform linux -- Python 3.14.6, pytest-9.1.1, pluggy-1.6.0 -- /home/penguin/source/hearth/.venv/bin/python
cachedir: .pytest_cache
rootdir: /home/penguin/.claude/jobs/f05ea59d/tmp/burrows/FTHR-010
configfile: pyproject.toml
plugins: asyncio-1.4.0, anyio-4.14.1
asyncio: mode=Mode.AUTO, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collecting ... collected 2 items

tests/test_brain_guard.py::test_nested_request_carries_guard_as_first_message FAILED [ 50%]
tests/test_brain_guard.py::test_guard_prompt_is_config_driven FAILED     [100%]

=================================== FAILURES ===================================
______________ test_nested_request_carries_guard_as_first_message ______________

    sent_messages = requests_seen[0]["messages"]
>   assert sent_messages[0] == {"role": "system", "content": guard}
E   AssertionError: assert {'role': 'use...Ada Lovelace'} == {'role': 'sys...ss the user.'}
E
E     Differing items:
E     {'content': 'who was Ada Lovelace'} != {'content': 'You are an internal research subsystem. Do not claim a name or address the user.'}
E     {'role': 'user'} != {'role': 'sys...

tests/test_brain_guard.py:55: AssertionError
______________________ test_guard_prompt_is_config_driven __________________________

>   assert requests_seen[0]["messages"][0]["content"] == guard
E   AssertionError: assert 'who was Ada Lovelace' == 'A wholly dif...to this test.'
E
E     - A wholly different guard string, unique to this test.
E     + who was Ada Lovelace

tests/test_brain_guard.py:75: AssertionError
=========================== short test summary info ============================
FAILED tests/test_brain_guard.py::test_nested_request_carries_guard_as_first_message - AssertionError: assert {'role': 'use...Ada Lovelace'} == {'role': 'sys...ss...
FAILED tests/test_brain_guard.py::test_guard_prompt_is_config_driven - AssertionError: assert 'who was Ada Lovelace' == 'A wholly dif...to this te...
============================== 2 failed in 0.03s ===============================
```

Both fail for the expected reason: `messages[0]` seeded by unchanged `BrainConsult.__call__` is the user query (`Message(role="user", content=query)`), not a guard-configured system message — because `PersonaConfig` had no `brain_guard_prompt` field yet and `consult.py` never prepended one.

### Post-implementation (passing)

Command: `.venv/bin/python -m pytest tests/test_brain_guard.py -v`

```
============================= test session starts ==============================
platform linux -- Python 3.14.6, pytest-9.1.1, pluggy-1.6.0 -- /home/penguin/source/hearth/.venv/bin/python
cachedir: .pytest_cache
rootdir: /home/penguin/.claude/jobs/f05ea59d/tmp/burrows/FTHR-010
configfile: pyproject.toml
plugins: asyncio-1.4.0, anyio-4.14.1
asyncio: mode=Mode.AUTO, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collecting ... collected 2 items

tests/test_brain_guard.py::test_nested_request_carries_guard_as_first_message PASSED [ 50%]
tests/test_brain_guard.py::test_guard_prompt_is_config_driven PASSED     [100%]

============================== 2 passed in 0.01s ===============================
```

Full suite (baseline 42 + 2 new = 44), all green:

```
44 passed in 0.12s
```

## AC-2
Every nested brain request driven through `BrainConsult` carries `persona.brain_guard_prompt` as `messages[0]`.

Implementation: `hearth/tools/consult.py`, `BrainConsult.__call__`:

```python
messages: list[Message] = [
    Message(role="system", content=self._config.persona.brain_guard_prompt),
    Message(role="user", content=query),
]
```

This seeds every nested ReAct round unconditionally — there is no code path in `BrainConsult.__call__` that constructs `messages` without the guard prepended first.

`test_nested_request_carries_guard_as_first_message` (in `tests/test_brain_guard.py`) asserts, against the real captured HTTP request body sent to the mocked remote backend:
- `messages[0] == {"role": "system", "content": <configured brain_guard_prompt>}`
- `messages[1] == {"role": "user", "content": "who was Ada Lovelace"}` (the seeded query)

See AC-1's passing run above for the green result.

## AC-3
The guard text instructs the brain not to assert an identity or address the user; verified by asserting the configured string is non-empty and is the literal content of `messages[0]`.

Configured default (`config.yaml` / `default-config.yaml`, `persona.brain_guard_prompt`):

```
You are an internal research subsystem, not the user-facing assistant.
Answer factually and concisely. Do not claim a name or personality, and
do not address "the user" directly -- your output is read by another
system, not a person.
```

Both `test_nested_request_carries_guard_as_first_message` and
`test_guard_prompt_is_config_driven` construct a non-empty `brain_guard_prompt`
and assert it is the literal `messages[0]["content"]` sent to the remote
backend — see AC-1's passing output above.

## AC-4
`persona.brain_guard_prompt` is config-driven (YAML default, `HEARTH_PERSONA__BRAIN_GUARD_PROMPT` env override), not hardcoded in `consult.py`.

- `hearth/config.py`: `PersonaConfig.brain_guard_prompt: str = ""` — no fallback string in Python; the default lives in YAML (matches `system_prompt`'s pattern from FTHR-009).
- `config.yaml` / `default-config.yaml`: `persona.brain_guard_prompt` set to the guard text, with an inline doc comment in `default-config.yaml`.
- `hearth/tools/consult.py` reads `self._config.persona.brain_guard_prompt` — no literal guard string in the module.

`test_guard_prompt_is_config_driven` constructs two `PersonaConfig`s with distinct `brain_guard_prompt` values and asserts the nested request's `messages[0]["content"]` reflects whichever config was injected — proving it isn't hardcoded. See AC-1's passing output above.

Env-var override verified directly against `Settings` (pydantic-settings), demonstrating the `HEARTH_PERSONA__BRAIN_GUARD_PROMPT` path documented in the spec:

Command:
```
HEARTH_PERSONA__BRAIN_GUARD_PROMPT="override text" .venv/bin/python -c "
from hearth.config import Settings
s = Settings()
print(repr(s.persona.brain_guard_prompt))
"
```

Output:
```
'override text'
```

Without the env var set, `Settings().persona.brain_guard_prompt` loads the `config.yaml` default via the existing `YamlConfigSettingsSource` precedence chain (unchanged from FTHR-009).

## Full suite + lint

```
$ .venv/bin/python -m pytest -q
44 passed in 0.12s

$ .venv/bin/ruff check .
All checks passed!
```
