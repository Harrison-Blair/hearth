# FTHR-011 molt evidence

## AC-1

Tests written: `tests/test_app_llm_diagnostics.py` (7 tests, pure helpers, no
daemon boot, no network) covering `_gateway_base_url` and
`_llm_unhealthy_warning`.

### Pre-implementation (FAILED — expected reason)

Command:
```
source /home/penguin/source/personal-assistant/.venv/bin/activate
python -m pytest tests/test_app_llm_diagnostics.py -v
```

Output:
```
============================= test session starts ==============================
platform linux -- Python 3.12.13, pytest-9.1.1, pluggy-1.6.0 -- /home/penguin/source/personal-assistant/.venv/bin/python
cachedir: .pytest_cache
rootdir: /home/penguin/source/personal-assistant/.fledge/burrows/FTHR-011
configfile: pyproject.toml
plugins: asyncio-1.4.0, anyio-4.14.1
asyncio: mode=Mode.AUTO, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collecting ... collected 0 items / 1 error

==================================== ERRORS ====================================
______________ ERROR collecting tests/test_app_llm_diagnostics.py ______________
ImportError while importing test module '/home/penguin/source/personal-assistant/.fledge/burrows/FTHR-011/tests/test_app_llm_diagnostics.py'.
Hint: make sure your test modules/packages have valid Python names.
Traceback:
/home/penguin/.pyenv/versions/3.12.13/lib/python3.12/importlib/__init__.py:90: in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
tests/test_app_llm_diagnostics.py:3: in <module>
    from assistant.app import _gateway_base_url, _llm_unhealthy_warning
E   ImportError: cannot import name '_gateway_base_url' from 'assistant.app' (/home/penguin/source/personal-assistant/.fledge/burrows/FTHR-011/assistant/app.py)
=============================== warnings summary ===============================
../../../.venv/lib/python3.12/site-packages/webrtcvad.py:1
  /home/penguin/source/personal-assistant/.venv/lib/python3.12/site-packages/webrtcvad.py:1: UserWarning: pkg_resources is deprecated as an API. See https://setuptools.pypa.io/en/latest/pkg_resources.html. The pkg_resources package is slated for removal as early as 2025-11-30. Refrain from using this package or pin to Setuptools<81.
    import pkg_resources

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
=========================== short test summary info ============================
ERROR tests/test_app_llm_diagnostics.py
!!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
========================= 1 warning, 1 error in 0.70s ==========================
```

Fails for the expected reason: `_gateway_base_url` (and `_llm_unhealthy_warning`)
do not exist in `assistant.app` yet.

### Post-implementation (PASSED)

Command:
```
source /home/penguin/source/personal-assistant/.venv/bin/activate
python -m pytest tests/test_app_llm_diagnostics.py -v
```

Output:
```
============================= test session starts ==============================
platform linux -- Python 3.12.13, pytest-9.1.1, pluggy-1.6.0 -- /home/penguin/source/personal-assistant/.venv/bin/python
cachedir: .pytest_cache
rootdir: /home/penguin/source/personal-assistant/.fledge/burrows/FTHR-011
configfile: pyproject.toml
plugins: asyncio-1.4.0, anyio-4.14.1
asyncio: mode=Mode.AUTO, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collecting ... collected 7 items

tests/test_app_llm_diagnostics.py::test_gateway_base_url_openrouter PASSED [ 14%]
tests/test_app_llm_diagnostics.py::test_gateway_base_url_opencode_zen PASSED [ 28%]
tests/test_app_llm_diagnostics.py::test_gateway_base_url_explicit_override PASSED [ 42%]
tests/test_app_llm_diagnostics.py::test_gateway_base_url_ollama_is_none PASSED [ 57%]
tests/test_app_llm_diagnostics.py::test_unhealthy_warning_openrouter_names_gateway PASSED [ 71%]
tests/test_app_llm_diagnostics.py::test_unhealthy_warning_opencode_zen_names_gateway PASSED [ 85%]
tests/test_app_llm_diagnostics.py::test_unhealthy_warning_ollama_gives_ollama_serve_message PASSED [100%]

=============================== warnings summary ===============================
../../../.venv/lib/python3.12/site-packages/webrtcvad.py:1
  /home/penguin/source/personal-assistant/.venv/lib/python3.12/site-packages/webrtcvad.py:1: UserWarning: pkg_resources is deprecated as an API. See https://setuptools.pypa.io/en/latest/pkg_resources.html. The pkg_resources package is slated for removal as early as 2025-11-30. Refrain from using this package or pin to Setuptools<81.
    import pkg_resources

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
======================== 7 passed, 1 warning in 0.64s =========================
```

## AC-2

With `provider: openrouter`, the boot "Config:" log endpoint and the
unhealthy-LLM warning are both driven by `GATEWAYS` via `_gateway_base_url` /
`_llm_unhealthy_warning`, naming OpenRouter and its base_url — verified
directly by the unit tests above:

- `test_gateway_base_url_openrouter`: `_gateway_base_url(LlmConfig(provider="openrouter", base_url=""))`
  == `GATEWAYS["openrouter"]["base_url"]` (`https://openrouter.ai/api/v1`).
  `main()`'s boot log line is `llm_endpoint = _gateway_base_url(config.llm) or config.llm.host`,
  so with `provider=openrouter` it resolves to that same URL (not `config.llm.host`).
- `test_unhealthy_warning_openrouter_names_gateway`: `_llm_unhealthy_warning(LlmConfig(provider="openrouter", ...))`
  contains `"openrouter"`, the OpenRouter base_url, and `"ASSISTANT_LLM__API_KEY"`.
  `_run()` logs `log.warning(_llm_unhealthy_warning(config.llm))` when the boot
  health check fails, so a down OpenRouter gateway logs this message, not a
  Zen-worded one.

No `== "opencode-zen"` string check remains in `main()`'s endpoint-selection
branch or `_run()`'s unhealthy-warning branch — confirmed by inspection of the
diff (see AC-3 command below) and by:

```
$ grep -n 'opencode-zen' assistant/app.py
```
```
(no output — provider name only appears as a dict key in GATEWAYS, imported from
assistant/llm/openai_compatible_provider.py, not compared with `==` in app.py)
```

## AC-3

`opencode-zen` and `ollama` diagnostics are unchanged in substance:

- **opencode-zen**: both `config.yaml` and `default-config.yaml` set
  `llm.base_url: https://opencode.ai/zen/v1` explicitly (never blank in
  practice), so `_gateway_base_url` resolves to the exact same string the old
  `config.llm.base_url if provider == "opencode-zen" else ...` expression
  produced. `test_gateway_base_url_opencode_zen` and
  `test_unhealthy_warning_opencode_zen_names_gateway` pin this: base_url ==
  `GATEWAYS["opencode-zen"]["base_url"]` and the warning still names
  `"opencode-zen"`, includes the same base_url, and the same
  `ASSISTANT_LLM__API_KEY` guidance as the prior Zen-specific message.
- **ollama**: `_gateway_base_url` returns `None` for `provider="ollama"`
  (`test_gateway_base_url_ollama_is_none`), so the boot log still falls back to
  `config.llm.host` exactly as before. `_llm_unhealthy_warning` reproduces the
  identical "Ollama not ready (host=..., model=...); ... Run \`ollama serve\`
  and \`ollama pull <model>\`." wording verbatim
  (`test_unhealthy_warning_ollama_gives_ollama_serve_message`).
- `tests/test_llm_dispatch.py` (pre-existing `_build_one_llm` gateway-resolution
  tests, unrelated to this feather but exercising the same refactored code path)
  all still pass unmodified — see AC-4 full-suite run.

## AC-4

Commands:
```
source /home/penguin/source/personal-assistant/.venv/bin/activate
ruff check assistant tests
python -m pytest
```

`ruff` output:
```
All checks passed!
```

`pytest` output (tail):
```
tests/test_tui_collapse.py ..                                            [ 73%]
tests/test_tui_config_schema.py ........                                 [ 74%]
tests/test_tui_configfile.py ....                                        [ 75%]
tests/test_tui_control.py ...                                            [ 75%]
tests/test_tui_discovery.py ........................................     [ 80%]
tests/test_tui_envfile.py ...                                            [ 80%]
tests/test_tui_logcolor.py .........                                     [ 81%]
tests/test_tui_logparse.py ......                                        [ 82%]
tests/test_tui_ollama.py ........                                        [ 83%]
tests/test_tui_reflow.py ..                                              [ 83%]
tests/test_tui_runlog.py .....                                           [ 84%]
tests/test_tui_screens.py ....................................           [ 88%]
tests/test_tui_selection.py ...                                          [ 88%]
tests/test_tui_supervisor.py .........                                   [ 89%]
tests/test_tui_widgets.py ..........                                     [ 90%]
tests/test_update_skill.py .....                                         [ 91%]
tests/test_verify.py .............................                       [ 94%]
tests/test_voice_download.py ...                                        [ 95%]
tests/test_wake_registry.py ...                                         [ 95%]
tests/test_weather_skill.py ....                                        [ 95%]
tests/test_web_search_skill.py ...........................              [ 98%]
tests/test_wikipedia_provider.py .........                              [100%]

================== 861 passed, 2 skipped, 1 warning in 22.27s ==================
```

No network access was used in any of the above (all tests are pure unit tests
over config/helper objects; no daemon boot).
