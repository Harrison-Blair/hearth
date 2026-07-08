# FTHR-013 evidence

## AC-1

Tests were written first and run against unchanged code; all 12 failed for the expected reasons.
After implementation all 12 pass, and the full suite is green.

### Pre-implementation failures (verbatim)

```
$ source /home/penguin/source/personal-assistant/.venv/bin/activate && \
  pytest tests/test_config.py::test_llm_config_has_no_api_key \
         tests/test_config.py::test_llm_per_provider_key_defaults \
         tests/test_config.py::test_env_file_loads_openrouter_api_key \
         tests/test_config.py::test_env_var_beats_env_file \
         tests/test_config.py::test_env_file_beats_yaml \
         tests/test_llm_dispatch.py \
         tests/test_app_llm_diagnostics.py -v

============================= test session starts ==============================
platform linux -- Python 3.12.13, pytest-9.1.1, pluggy-1.6.0
asyncio: mode=Mode.AUTO
collected 20 items

tests/test_config.py::test_llm_config_has_no_api_key FAILED
tests/test_config.py::test_llm_per_provider_key_defaults FAILED
tests/test_config.py::test_env_file_loads_openrouter_api_key FAILED
tests/test_config.py::test_env_var_beats_env_file FAILED
tests/test_config.py::test_env_file_beats_yaml FAILED
tests/test_llm_dispatch.py::test_openrouter_resolves_to_openrouter_base_url PASSED
tests/test_llm_dispatch.py::test_opencode_zen_resolves_to_zen_base_url FAILED
tests/test_llm_dispatch.py::test_blank_base_url_uses_table_default PASSED
tests/test_llm_dispatch.py::test_explicit_base_url_overrides_table_default PASSED
tests/test_llm_dispatch.py::test_unknown_provider_falls_back_to_ollama PASSED
tests/test_llm_dispatch.py::test_openrouter_uses_openrouter_api_key FAILED
tests/test_llm_dispatch.py::test_opencode_zen_uses_opencode_zen_api_key FAILED
tests/test_llm_dispatch.py::test_old_opencode_zen_hyphen_key_absent FAILED
tests/test_app_llm_diagnostics.py::test_gateway_base_url_openrouter PASSED
tests/test_app_llm_diagnostics.py::test_gateway_base_url_opencode_zen FAILED
tests/test_app_llm_diagnostics.py::test_gateway_base_url_explicit_override PASSED
tests/test_app_llm_diagnostics.py::test_gateway_base_url_ollama_is_none PASSED
tests/test_app_llm_diagnostics.py::test_unhealthy_warning_openrouter_names_gateway FAILED
tests/test_app_llm_diagnostics.py::test_unhealthy_warning_opencode_zen_names_gateway FAILED
tests/test_app_llm_diagnostics.py::test_unhealthy_warning_ollama_gives_ollama_serve_message PASSED

FAILED tests/test_config.py::test_llm_config_has_no_api_key - assert not True
FAILED tests/test_config.py::test_llm_per_provider_key_defaults - AttributeError: 'LlmConfig' object has no attribute 'openrouter_api_key'
FAILED tests/test_config.py::test_env_file_loads_openrouter_api_key - AttributeError: 'LlmConfig' object has no attribute 'openrouter_api_key'
FAILED tests/test_config.py::test_env_var_beats_env_file - AttributeError: 'LlmConfig' object has no attribute 'openrouter_api_key'
FAILED tests/test_config.py::test_env_file_beats_yaml - AttributeError: 'LlmConfig' object has no attribute 'openrouter_api_key'
FAILED tests/test_llm_dispatch.py::test_opencode_zen_resolves_to_zen_base_url - AssertionError (provider not in GATEWAYS)
FAILED tests/test_llm_dispatch.py::test_openrouter_uses_openrouter_api_key - AssertionError: cfg.openrouter_api_key doesn't exist
FAILED tests/test_llm_dispatch.py::test_opencode_zen_uses_opencode_zen_api_key - isinstance check failed (fell back to OllamaProvider)
FAILED tests/test_llm_dispatch.py::test_old_opencode_zen_hyphen_key_absent - 'opencode-zen' was in GATEWAYS
FAILED tests/test_app_llm_diagnostics.py::test_gateway_base_url_opencode_zen - KeyError: 'opencode_zen'
FAILED tests/test_app_llm_diagnostics.py::test_unhealthy_warning_openrouter_names_gateway - 'ASSISTANT_LLM__OPENROUTER_API_KEY' not in msg
FAILED tests/test_app_llm_diagnostics.py::test_unhealthy_warning_opencode_zen_names_gateway - 'opencode_zen' not in msg

12 failed, 8 passed, 1 warning in 0.57s
```

### Post-implementation run (all 20 pass)

```
$ pytest tests/test_config.py::test_llm_config_has_no_api_key \
         tests/test_config.py::test_llm_per_provider_key_defaults \
         tests/test_config.py::test_env_file_loads_openrouter_api_key \
         tests/test_config.py::test_env_var_beats_env_file \
         tests/test_config.py::test_env_file_beats_yaml \
         tests/test_llm_dispatch.py \
         tests/test_app_llm_diagnostics.py -v

collected 20 items

tests/test_config.py::test_llm_config_has_no_api_key PASSED
tests/test_config.py::test_llm_per_provider_key_defaults PASSED
tests/test_config.py::test_env_file_loads_openrouter_api_key PASSED
tests/test_config.py::test_env_var_beats_env_file PASSED
tests/test_config.py::test_env_file_beats_yaml PASSED
tests/test_llm_dispatch.py::test_openrouter_resolves_to_openrouter_base_url PASSED
tests/test_llm_dispatch.py::test_opencode_zen_resolves_to_zen_base_url PASSED
tests/test_llm_dispatch.py::test_blank_base_url_uses_table_default PASSED
tests/test_llm_dispatch.py::test_explicit_base_url_overrides_table_default PASSED
tests/test_llm_dispatch.py::test_unknown_provider_falls_back_to_ollama PASSED
tests/test_llm_dispatch.py::test_openrouter_uses_openrouter_api_key PASSED
tests/test_llm_dispatch.py::test_opencode_zen_uses_opencode_zen_api_key PASSED
tests/test_llm_dispatch.py::test_old_opencode_zen_hyphen_key_absent PASSED
tests/test_app_llm_diagnostics.py::test_gateway_base_url_openrouter PASSED
tests/test_app_llm_diagnostics.py::test_gateway_base_url_opencode_zen PASSED
tests/test_app_llm_diagnostics.py::test_gateway_base_url_explicit_override PASSED
tests/test_app_llm_diagnostics.py::test_gateway_base_url_ollama_is_none PASSED
tests/test_app_llm_diagnostics.py::test_unhealthy_warning_openrouter_names_gateway PASSED
tests/test_app_llm_diagnostics.py::test_unhealthy_warning_opencode_zen_names_gateway PASSED
tests/test_app_llm_diagnostics.py::test_unhealthy_warning_ollama_gives_ollama_serve_message PASSED

20 passed, 1 warning in 0.71s
```

## AC-2

`.env` is wired via `env_file=".env"` in `SettingsConfigDict` and `dotenv_settings` added to the
source tuple (precedence: init > env > .env > yaml). Tests `test_env_file_loads_openrouter_api_key`,
`test_env_var_beats_env_file`, and `test_env_file_beats_yaml` exercise all three precedence edges.

```
$ pytest tests/test_config.py::test_env_file_loads_openrouter_api_key \
         tests/test_config.py::test_env_var_beats_env_file \
         tests/test_config.py::test_env_file_beats_yaml -v

3 passed in 0.29s
```

## AC-3

`LlmConfig.api_key` removed; `openrouter_api_key` and `opencode_zen_api_key` added.
`_build_one_llm` resolves `key = getattr(cfg, f"{provider}_api_key", "")`.

```
$ pytest tests/test_config.py::test_llm_config_has_no_api_key \
         tests/test_config.py::test_llm_per_provider_key_defaults \
         tests/test_llm_dispatch.py::test_openrouter_uses_openrouter_api_key \
         tests/test_llm_dispatch.py::test_opencode_zen_uses_opencode_zen_api_key -v

4 passed in 0.17s
```

## AC-4

`GATEWAYS["opencode_zen"]` resolves to `https://opencode.ai/zen/v1`; `"opencode-zen"` key absent.
Diagnostics message names `opencode_zen` and the per-provider env var.

```
$ pytest tests/test_llm_dispatch.py::test_opencode_zen_resolves_to_zen_base_url \
         tests/test_llm_dispatch.py::test_old_opencode_zen_hyphen_key_absent \
         tests/test_app_llm_diagnostics.py::test_gateway_base_url_opencode_zen \
         tests/test_app_llm_diagnostics.py::test_unhealthy_warning_opencode_zen_names_gateway -v

4 passed in 0.09s
```

Note: `tui/app.py:_probe_provider` still checks `name == "opencode-zen"` (dead code path
now that no config uses that string) — the TUI health-probe rename is FTHR-014's scope.
One line in `tui/app.py:_select_options` was updated from `api_key=llm.api_key` to
`api_key=getattr(llm, f"{llm.provider}_api_key", "")` because removing `LlmConfig.api_key`
broke 3 TUI tests required by AC-5; this is the minimum change needed.

## AC-5

```
$ ruff check assistant tests
All checks passed!

$ pytest
865 passed, 2 skipped, 1 warning in 28.79s
```
