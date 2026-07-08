# FTHR-010 molt evidence

Summary: moved `OpenCodeZenProvider` (`assistant/llm/opencode_zen_provider.py`)
to a vendor-neutral `OpenAICompatibleProvider`
(`assistant/llm/openai_compatible_provider.py`), added an additive
`extra_headers: dict[str, str] | None = None` constructor param merged onto the
bearer-auth headers, and defined a `GATEWAYS` table (`opencode-zen` ->
`https://opencode.ai/zen/v1`, `openrouter` -> `https://openrouter.ai/api/v1`,
both with empty `extra_headers`). `assistant/app.py:_build_one_llm` now
dispatches on `provider in GATEWAYS`, building `OpenAICompatibleProvider` with
`base_url = cfg.base_url or GATEWAYS[provider]["base_url"]` and that gateway's
`extra_headers`; the `ollama` else-branch and the diagnostic branches in
`_run`/`main` are untouched. `assistant/core/config.py:LlmConfig.base_url`
default changed from the hardcoded Zen URL to `""` (blank = table default).
`tests/test_zen_provider.py` / `_guards.py` were renamed to
`tests/test_openai_compatible_provider.py` / `_guards.py` and repointed to
`OpenAICompatibleProvider` (proves backward-compat, not assumed). A new
`tests/test_llm_dispatch.py` unit-tests `_build_one_llm`'s gateway-table
resolution with no network.

## AC-1

Tests observed failing before implementation (module didn't exist yet),
passing after.

Command (pre-implementation, unchanged code — test files already renamed and
repointed to the not-yet-existing `OpenAICompatibleProvider`/`GATEWAYS`):

```
source .venv/bin/activate && python -m pytest \
  tests/test_openai_compatible_provider.py \
  tests/test_openai_compatible_provider_guards.py \
  tests/test_llm_dispatch.py -q
```

Verbatim output (FAILING — collection errors, `ModuleNotFoundError: No module
named 'assistant.llm.openai_compatible_provider'`):

```
==================================== ERRORS ====================================
__________ ERROR collecting tests/test_openai_compatible_provider.py ___________
ImportError while importing test module '/home/penguin/source/personal-assistant/.fledge/burrows/FTHR-010/tests/test_openai_compatible_provider.py'.
Hint: make sure your test modules/packages have valid Python names.
Traceback:
/home/penguin/.pyenv/versions/3.12.13/lib/python3.12/importlib/__init__.py:90: in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
tests/test_openai_compatible_provider.py:5: in <module>
    from assistant.llm.openai_compatible_provider import OpenAICompatibleProvider
E   ModuleNotFoundError: No module named 'assistant.llm.openai_compatible_provider'
_______ ERROR collecting tests/test_openai_compatible_provider_guards.py _______
ImportError while importing test module '/home/penguin/source/personal-assistant/.fledge/burrows/FTHR-010/tests/test_openai_compatible_provider_guards.py'.
Hint: make sure your test modules/packages have valid Python names.
Traceback:
/home/penguin/.pyenv/versions/3.12.13/lib/python3.12/importlib/__init__.py:90: in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
tests/test_openai_compatible_provider_guards.py:15: in <module>
    from assistant.llm.openai_compatible_provider import LLMResponseError, OpenAICompatibleProvider
E   ModuleNotFoundError: No module named 'assistant.llm.openai_compatible_provider'
_________________ ERROR collecting tests/test_llm_dispatch.py __________________
ImportError while importing test module '/home/penguin/source/personal-assistant/.fledge/burrows/FTHR-010/tests/test_llm_dispatch.py'.
Hint: make sure your test modules/packages have valid Python names.
Traceback:
/home/penguin/.pyenv/versions/3.12.13/lib/python3.12/importlib/__init__.py:90: in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
tests/test_llm_dispatch.py:6: in <module>
    from assistant.llm.openai_compatible_provider import GATEWAYS, OpenAICompatibleProvider
E   ModuleNotFoundError: No module named 'assistant.llm.openai_compatible_provider'
=============================== warnings summary ===============================
../../../.venv/lib/python3.12/site-packages/webrtcvad.py:1
  /home/penguin/source/personal-assistant/.venv/lib/python3.12/site-packages/webrtcvad.py:1: UserWarning: pkg_resources is deprecated as an API. See https://setuptools.pypa.io/en/latest/pkg_resources.html. The pkg_resources package is slated for removal as early as 2025-11-30. Refrain from using this package or pin to Setuptools<81.
    import pkg_resources

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
=========================== short test summary info ============================
ERROR tests/test_openai_compatible_provider.py
ERROR tests/test_openai_compatible_provider_guards.py
ERROR tests/test_llm_dispatch.py
!!!!!!!!!!!!!!!!!!! Interrupted: 3 errors during collection !!!!!!!!!!!!!!!!!!!!
1 warning, 3 errors in 0.49s
```

Command (post-implementation, same test files, same command):

```
source .venv/bin/activate && python -m pytest \
  tests/test_openai_compatible_provider.py \
  tests/test_openai_compatible_provider_guards.py \
  tests/test_llm_dispatch.py -q
```

Verbatim output (PASSING):

```
................................................                         [100%]
=============================== warnings summary ===============================
../../../.venv/lib/python3.12/site-packages/webrtcvad.py:1
  /home/penguin/source/personal-assistant/.venv/lib/python3.12/site-packages/webrtcvad.py:1: UserWarning: pkg_resources is deprecated as an API. See https://setuptools.pypa.io/en/latest/pkg_resources.html. The pkg_resources package is slated for removal as early as 2025-11-30. Refrain from using this package or pin to Setuptools<81.
    import pkg_resources

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
48 passed, 1 warning in 0.72s
```

## AC-2

The repointed Zen wire + retry/guard suites (43 tests, unchanged assertions
except the class name) pass unchanged against `OpenAICompatibleProvider`.
`test_llm_dispatch.py::test_opencode_zen_resolves_to_zen_base_url` confirms
`provider: opencode-zen` still builds `OpenAICompatibleProvider` targeting the
Zen base URL end-to-end via `_build_one_llm`.

Command:

```
source .venv/bin/activate && python -m pytest \
  tests/test_openai_compatible_provider.py \
  tests/test_openai_compatible_provider_guards.py -q
```

Verbatim output:

```
...........................................                              [100%]
43 passed in 0.11s
```

## AC-3

`GATEWAYS` table resolution unit-tested directly against `_build_one_llm`, no
network: `openrouter` -> OpenRouter base URL, `opencode-zen` -> Zen base URL,
blank `cfg.base_url` uses the table default, explicit `cfg.base_url` overrides
it, and an unrecognized provider still falls back to `OllamaProvider`.

Command:

```
source .venv/bin/activate && python -m pytest tests/test_llm_dispatch.py -q
```

Verbatim output:

```
.....                                                                    [100%]
=============================== warnings summary ===============================
../../../.venv/lib/python3.12/site-packages/webrtcvad.py:1
  /home/penguin/source/personal-assistant/.venv/lib/python3.12/site-packages/webrtcvad.py:1: UserWarning: pkg_resources is deprecated as an API. See https://setuptools.pypa.io/en/latest/pkg_resources.html. The pkg_resources package is slated for removal as early as 2025-11-30. Refrain from using this package or pin to Setuptools<81.
    import pkg_resources

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
5 passed, 1 warning in 0.34s
```

## AC-4

`test_llm_dispatch.py::test_openrouter_resolves_to_openrouter_base_url` proves
`provider: openrouter` with a key builds an `OpenAICompatibleProvider`
targeting OpenRouter. `test_openai_compatible_provider.py` proves the generic
provider sends any configured model verbatim
(`test_generic_model_sent_verbatim`), declares `tools` on `chat_tools`
(`test_generic_chat_tools_declares_tools_feature`), declares
`response_format` on `complete(json=True)`
(`test_generic_complete_json_declares_response_format_feature`), and merges
`extra_headers` onto bearer auth (`test_extra_headers_merge_onto_auth`,
`test_extra_headers_none_leaves_auth_untouched`,
`test_extra_headers_empty_leaves_auth_untouched`).

Command:

```
source .venv/bin/activate && python -m pytest \
  tests/test_openai_compatible_provider.py -k "extra_headers or generic" -q
```

Verbatim output:

```
......                                                                   [100%]
6 passed, 20 deselected in 0.05s
```

## AC-5

`ruff check assistant tests` and the full suite pass, no network (remote wire
tests use `httpx.MockTransport`; `test_llm_dispatch.py` never calls `.health()`
or any wire method, only inspects constructed attributes, then `aclose()`s the
pooled `httpx.AsyncClient` without ever sending a request).

Command:

```
source .venv/bin/activate && ruff check assistant tests
```

Verbatim output:

```
All checks passed!
```

Command:

```
source .venv/bin/activate && python -m pytest -q
```

Verbatim output:

```
........................................................................ [  8%]
........................................................................ [ 16%]
........................................................................ [ 25%]
........................................................................ [ 33%]
........................................................................ [ 42%]
........................................................................ [ 50%]
........................................................................ [ 58%]
........................................................................ [ 67%]
........................................................................ [ 75%]
........................................................................ [ 84%]
........................................................................ [ 92%]
................................................................         [100%]
=============================== warnings summary ===============================
../../../.venv/lib/python3.12/site-packages/webrtcvad.py:1
  /home/penguin/source/personal-assistant/.venv/lib/python3.12/site-packages/webrtcvad.py:1: UserWarning: pkg_resources is deprecated as an API. See https://setuptools.pypa.io/en/latest/pkg_resources.html. The pkg_resources package is slated for removal as early as 2025-11-30. Refrain from using this package or pin to Setuptools<81.
    import pkg_resources

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
854 passed, 2 skipped, 1 warning in 21.60s
```
