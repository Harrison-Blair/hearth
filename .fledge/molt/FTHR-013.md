# FTHR-013 evidence

## AC-1

Tests were written first and run against unchanged code; all 12 daemon-side tests failed for the
expected reasons. After implementation all 12 pass. The TUI tests (8 new failures from the
test-first update) were similarly confirmed failing before the TUI implementation, then made green.

### Pre-implementation failures — daemon side (verbatim)

```
$ pytest tests/test_config.py::test_llm_config_has_no_api_key \
         tests/test_config.py::test_llm_per_provider_key_defaults \
         tests/test_config.py::test_env_file_loads_openrouter_api_key \
         tests/test_config.py::test_env_var_beats_env_file \
         tests/test_config.py::test_env_file_beats_yaml \
         tests/test_llm_dispatch.py \
         tests/test_app_llm_diagnostics.py -v

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
FAILED tests/test_config.py::test_env_file_loads_openrouter_api_key - AttributeError
FAILED tests/test_config.py::test_env_var_beats_env_file - AttributeError
FAILED tests/test_config.py::test_env_file_beats_yaml - AttributeError
FAILED tests/test_llm_dispatch.py::test_opencode_zen_resolves_to_zen_base_url - AssertionError
FAILED tests/test_llm_dispatch.py::test_openrouter_uses_openrouter_api_key - AssertionError
FAILED tests/test_llm_dispatch.py::test_opencode_zen_uses_opencode_zen_api_key - isinstance check failed
FAILED tests/test_llm_dispatch.py::test_old_opencode_zen_hyphen_key_absent - 'opencode-zen' was in GATEWAYS
FAILED tests/test_app_llm_diagnostics.py::test_gateway_base_url_opencode_zen - KeyError: 'opencode_zen'
FAILED tests/test_app_llm_diagnostics.py::test_unhealthy_warning_openrouter_names_gateway - 'ASSISTANT_LLM__OPENROUTER_API_KEY' not in msg
FAILED tests/test_app_llm_diagnostics.py::test_unhealthy_warning_opencode_zen_names_gateway - 'opencode_zen' not in msg

12 failed, 8 passed, 1 warning in 0.57s
```

### Post-implementation run — daemon tests (20/20 pass)

```
$ pytest tests/test_config.py::test_llm_config_has_no_api_key \
         tests/test_config.py::test_llm_per_provider_key_defaults \
         tests/test_config.py::test_env_file_loads_openrouter_api_key \
         tests/test_config.py::test_env_var_beats_env_file \
         tests/test_config.py::test_env_file_beats_yaml \
         tests/test_llm_dispatch.py \
         tests/test_app_llm_diagnostics.py -v

20 passed, 1 warning in 0.71s
```

### Pre-implementation failures — TUI side (8 tests, verbatim summary)

Updated TUI tests to use `"opencode_zen"` and `opencode_zen_api_key`, then ran against unchanged
`tui/` source — 8 tests failed:

```
FAILED tests/test_tui_app.py::test_provider_label_shortens_zen - AssertionError
FAILED tests/test_tui_app.py::test_llm_status_line_provider_aware - AssertionError
FAILED tests/test_tui_app.py::test_check_llm_health_routes_probes_and_derives_tier
FAILED tests/test_tui_app.py::test_check_llm_health_no_fallback_skips_second_probe
FAILED tests/test_tui_discovery.py::test_llm_provider_options_static - AssertionError
FAILED tests/test_tui_discovery.py::test_llm_fallback_options_static_includes_none
FAILED tests/test_tui_discovery.py::test_llm_model_options_routes_to_zen - AssertionError
FAILED tests/test_tui_discovery.py::test_llm_fallback_model_options_routes_by_fallback_provider

8 failed (opencode-zen still in tui/ source)
```

## AC-2

`.env` is wired via `env_file=".env"` in `SettingsConfigDict` and `dotenv_settings` added to the
source tuple (precedence: init > env > .env > yaml). Tests exercise all three precedence edges.

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

## AC-5

No `"opencode-zen"` literal remains in `tui/`. `_provider_label`, `_probe_provider`,
`_select_options`, and `_on_model_detail_requested` (app.py), plus `llm_provider_options`,
`llm_fallback_options`, `llm_model_options`, `llm_fallback_model_options` (discovery.py) all
match `"opencode_zen"`. `_probe_provider` passes `llm.opencode_zen_api_key` to `zen_health`.
`_select_options` resolves `getattr(llm, f"{llm.provider}_api_key", "")`.

```
$ grep -rn "opencode-zen" tui/ tests/test_tui_app.py tests/test_tui_discovery.py tests/test_tui_screens.py
(no output — CLEAN)

$ pytest tests/test_tui_app.py tests/test_tui_discovery.py tests/test_tui_screens.py -v 2>&1 | tail -3
104 passed, 2 skipped, 1 warning in 5.47s
```

## AC-6

```
$ ruff check assistant tests tui
All checks passed!

$ pytest
873 passed, 2 skipped, 1 warning in 21.97s
```

### Test isolation fix (post-merge red-path)

After merging into `main`, `tests/test_config.py::test_loads_yaml_and_overrides_defaults` failed
on the main repo because a real `.env` (containing `ASSISTANT_STT__MODEL=base.en`) sat in the
working directory. The feature is correct — `.env` overrides `config.yaml` — but tests must be
isolated from a developer's machine environment.

**Reproduce:** place `ASSISTANT_STT__MODEL=base.en` in a worktree `.env`, run
`pytest tests/test_config.py -q` → 1 failure (`'base.en' != 'medium'`).

**Fix:** `tests/conftest.py` (new file) — autouse fixture that sets
`Config.model_config["env_file"] = None` via `monkeypatch`, neutralizing any CWD `.env` for
the whole suite. Tests that explicitly exercise `.env` loading pass `Config(_env_file=<tmp>)`,
which overrides the fixture; those tests remain meaningful and green.

**Verify:** with the throwaway `.env` still present → `ruff check assistant tests tui` clean +
`pytest` 873 passed. Remove throwaway `.env`, confirm same result.
