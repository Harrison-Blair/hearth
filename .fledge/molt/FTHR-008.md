# FTHR-008 molt evidence: Typed BrainError crash-hardening

## AC-1

Tests observed failing before implementation, then passing after.

### Pre-implementation (unmodified `openai_compat.py`, `hearth/brain/errors.py` did not exist yet)

Command:
```
cd <worktree>
/home/penguin/source/hearth/.venv/bin/python -m pytest -q tests/test_brain_errors.py
```

Output:
```
==================================== ERRORS ====================================
_________________ ERROR collecting tests/test_brain_errors.py __________________
ImportError while importing test module '.../tests/test_brain_errors.py'.
Hint: make sure your test modules/packages have valid Python names.
Traceback:
/usr/lib/python3.14/importlib/__init__.py:88: in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
tests/test_brain_errors.py:8: in <module>
    from hearth.brain.errors import BrainError
E   ModuleNotFoundError: No module named 'hearth.brain.errors'
=========================== short test summary info ============================
ERROR tests/test_brain_errors.py
!!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
1 error in 0.05s
```

This confirms the tests fail for the expected reason (the curated `BrainError` type does not
exist yet, so the module cannot even be imported — collection fails before any of the raw
`httpx`/`KeyError`/`json.JSONDecodeError` exceptions get a chance to surface, which is exactly
what the "no BrainError yet" starting state predicts).

### Post-implementation (after adding `hearth/brain/errors.py` and wrapping the three raise
sources in `hearth/brain/openai_compat.py`)

Command:
```
cd <worktree>
/home/penguin/source/hearth/.venv/bin/python -m pytest -q tests/test_brain_errors.py
```

Output:
```
....                                                                     [100%]
4 passed in 0.01s
```

Note on tooling: the bare `pytest` console script does not add the worktree cwd to
`sys.path` early enough and resolves `hearth` from the main repo's editable install
instead of the worktree; `python -m pytest` was used throughout instead, which does
add cwd to `sys.path` and correctly resolves the worktree's `hearth` package
(verified via `python -c "import hearth; print(hearth.__file__)"` pointing inside the
worktree).

## AC-2

HTTP 500 (or transport failure) raises `BrainError`, not `httpx.HTTPStatusError`; `.reason` is
a curated "backend unreachable" string; `.detail` contains the status/exception text.

Covered by `tests/test_brain_errors.py::test_http_error_raises_brain_error`:
- MockTransport returns `httpx.Response(500, text="internal server error")`.
- Asserts `BrainError` is raised (not `httpx.HTTPStatusError`).
- Asserts `.reason == "backend unreachable"`.
- Asserts `"500" in .detail`.

Command:
```
/home/penguin/source/hearth/.venv/bin/python -m pytest -q tests/test_brain_errors.py::test_http_error_raises_brain_error
```
Output:
```
.                                                                        [100%]
1 passed in 0.01s
```

Implementation: `hearth/brain/openai_compat.py` wraps the `self._client.post(...)` call and
`response.raise_for_status()` in `try/except httpx.HTTPError as exc: raise BrainError("backend
unreachable", detail=str(exc)) from exc` — `httpx.HTTPError` is the shared base for both
`httpx.HTTPStatusError` (raised by `raise_for_status()`) and transport-level errors raised by
`post()`.

## AC-3

A malformed response body (missing `choices`) raises `BrainError` with an "unreadable response"
reason, not a raw `KeyError`/`IndexError`.

Covered by `tests/test_brain_errors.py::test_malformed_body_raises_brain_error`:
- MockTransport returns 200 with `{"nope": "no choices here"}` (no `choices` key).
- Asserts `BrainError` is raised with `.reason == "unreadable response"`.

Command:
```
/home/penguin/source/hearth/.venv/bin/python -m pytest -q tests/test_brain_errors.py::test_malformed_body_raises_brain_error
```
Output:
```
.                                                                        [100%]
1 passed in 0.01s
```

Implementation: `body["choices"][0]` / `choice["message"]` wrapped in
`try/except (KeyError, IndexError) as exc: raise BrainError("unreadable response", detail=...)
from exc`.

## AC-4

A tool-call with non-JSON `arguments` raises `BrainError`, not a raw `json.JSONDecodeError`.

Covered by `tests/test_brain_errors.py::test_bad_tool_arguments_raises_brain_error`:
- MockTransport returns a 200 body with a `tool_calls` entry whose `arguments` is the literal
  string `"{not valid json"` (not parseable JSON).
- Asserts `BrainError` is raised with `.reason == "unreadable response"`.

Command:
```
/home/penguin/source/hearth/.venv/bin/python -m pytest -q tests/test_brain_errors.py::test_bad_tool_arguments_raises_brain_error
```
Output:
```
.                                                                        [100%]
1 passed in 0.01s
```

Implementation: the tool-call list comprehension (`json.loads(tc["function"]["arguments"])`)
wrapped in `try/except json.JSONDecodeError as exc: raise BrainError("unreadable response",
detail=...) from exc`.

## AC-5

Neither `.reason` nor `.detail` on any raised `BrainError` ever contains the API key or
`Authorization` header value; `tests/test_local_backend.py` and `tests/test_remote_backend.py`
still pass unmodified (success path unchanged).

Covered by `tests/test_brain_errors.py::test_brain_error_never_leaks_api_key`:
- Constructs a `RemoteBackend` with a resolvable API key (`HEARTH_LLM__OPENROUTER_API_KEY` =
  `"sk-super-secret-123"`, sent as `Authorization: Bearer sk-super-secret-123` on every
  request per `test_remote_backend.py`'s existing pattern).
- Forces an HTTP 500 to trigger a `BrainError`.
- Asserts the secret string appears in none of `.reason`, `.detail`, or `str(exc)`.

Command:
```
/home/penguin/source/hearth/.venv/bin/python -m pytest -q tests/test_brain_errors.py::test_brain_error_never_leaks_api_key
```
Output:
```
.                                                                        [100%]
1 passed in 0.01s
```

By construction, `BrainError.detail` is only ever built from `str(exc)` (the httpx exception,
which does not include request/response headers), `body!r` (the parsed JSON response body), or
the `json.JSONDecodeError` message — never from `headers` or `self._config`/`resolve_api_key()`.

Regression — existing success-path tests untouched and still passing:
```
/home/penguin/source/hearth/.venv/bin/python -m pytest -q tests/test_local_backend.py tests/test_remote_backend.py
```
```
...                                                                      [100%]
3 passed in 0.01s
```

## Full suite + lint

```
/home/penguin/source/hearth/.venv/bin/python -m pytest -q
```
```
.....................................                                    [100%]
37 passed in 0.14s
```

```
/home/penguin/source/hearth/.venv/bin/ruff check .
```
```
All checks passed!
```
