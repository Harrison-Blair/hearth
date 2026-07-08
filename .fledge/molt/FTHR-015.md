# FTHR-015 evidence

## AC-1

Tests were written first and run against unchanged files; all 4 failed for the expected reasons.
After implementation all 4 pass.

### Pre-implementation failures (verbatim)

```
$ cd .fledge/burrows/FTHR-015 && pytest tests/test_no_secrets_in_config.py -v

collected 4 items

tests/test_no_secrets_in_config.py::test_no_secrets_in_config_yaml FAILED
tests/test_no_secrets_in_config.py::test_no_secrets_in_default_config_yaml FAILED
tests/test_no_secrets_in_config.py::test_env_example_contains_required_cred_vars FAILED
tests/test_no_secrets_in_config.py::test_env_example_has_no_non_secret_assistant_vars FAILED

FAILED test_no_secrets_in_config_yaml - AssertionError: config.yaml has secret-bearing fields: ['llm.api_key', 'web_search.tavily_api_key', 'web_search.exa_api_key']
FAILED test_no_secrets_in_default_config_yaml - AssertionError: default-config.yaml has secret-bearing fields: ['llm.api_key', 'web_search.tavily_api_key', 'web_search.exa_api_key']
FAILED test_env_example_contains_required_cred_vars - AssertionError: .env.example missing credential vars: {'ASSISTANT_WEB_SEARCH__TAVILY_API_KEY', 'ASSISTANT_WEB_SEARCH__EXA_API_KEY', 'ASSISTANT_LLM__OPENCODE_ZEN_API_KEY', 'ASSISTANT_LLM__OPENROUTER_API_KEY'}
FAILED test_env_example_has_no_non_secret_assistant_vars - AssertionError: .env.example contains non-secret ASSISTANT_* vars: {'ASSISTANT_WAKE__PHRASE', 'ASSISTANT_AUDIO__OUTPUT_VOLUME', 'ASSISTANT_LLM__FALLBACK', ... (18 vars)}

4 failed in 0.09s
```

### Post-implementation run (all 4 pass)

```
$ pytest tests/test_no_secrets_in_config.py -v

collected 4 items

tests/test_no_secrets_in_config.py::test_no_secrets_in_config_yaml PASSED
tests/test_no_secrets_in_config.py::test_no_secrets_in_default_config_yaml PASSED
tests/test_no_secrets_in_config.py::test_env_example_contains_required_cred_vars PASSED
tests/test_no_secrets_in_config.py::test_env_example_has_no_non_secret_assistant_vars PASSED

4 passed in 0.10s
```

## AC-2

`config.yaml` and `default-config.yaml` contain no secret-bearing fields.
- `llm.api_key` removed; replaced with `# api keys → .env; see .env.example`
- `web_search.tavily_api_key` and `web_search.exa_api_key` removed; same pointer comment
- `default-config.yaml` comment updated: `opencode-zen` → `opencode_zen`

```
$ pytest tests/test_no_secrets_in_config.py::test_no_secrets_in_config_yaml \
         tests/test_no_secrets_in_config.py::test_no_secrets_in_default_config_yaml -v

2 passed in 0.07s
```

## AC-3

`.env.example` rewritten: 4 credential vars only, no non-secret `ASSISTANT_*` overrides.

```
$ pytest tests/test_no_secrets_in_config.py::test_env_example_contains_required_cred_vars \
         tests/test_no_secrets_in_config.py::test_env_example_has_no_non_secret_assistant_vars -v

2 passed in 0.04s
```

## AC-4

```
$ ruff check assistant tests tui
All checks passed!

$ pytest
877 passed, 2 skipped, 1 warning in 22.96s
```
