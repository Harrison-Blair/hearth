# FTHR-022 — Molt evidence

Feather: Shared config facility and per-component config directory
Branch: `feather/FTHR-022-shared-config-facility`
Test runner: `/home/penguin/source/hearth/.venv/bin/python -m pytest` run from the
worktree root (per repo memory: module form so cwd shadows the editable install and
we test the worktree's `hearth`, not main's).

## AC-1

The tests listed in the spec were written first and observed FAILING against the
unchanged code, then PASSING after implementation.

### Pre-implementation (unchanged `hearth/config.py`)

Command:

```
python -m pytest tests/test_config.py
```

Verbatim summary:

```
=========================== short test summary info ============================
FAILED tests/test_config.py::test_cwd_config_used_when_packaged_default_missing
FAILED tests/test_config.py::test_no_config_anywhere_fails_loud - AttributeEr...
FAILED tests/test_config.py::test_resolver_targets_named_component_file[engine]
FAILED tests/test_config.py::test_resolver_targets_named_component_file[chat]
FAILED tests/test_config.py::test_missing_component_config_fails_loud - TypeE...
FAILED tests/test_config.py::test_engine_config_exposes_gateway_section - Att...
FAILED tests/test_config.py::test_default_persona_prompt_is_vesta - FileNotFo...
FAILED tests/test_config.py::test_default_persona_prompt_has_no_mythological_titles
FAILED tests/test_config.py::test_default_persona_prompt_has_deescalation_rule
FAILED tests/test_config.py::test_default_persona_prompt_retains_consult_brain_instruction
ERROR tests/test_config.py::test_config_loads_yaml_base - AttributeError: 'mo...
ERROR tests/test_config.py::test_env_overrides_yaml - AttributeError: 'module...
ERROR tests/test_config.py::test_secret_from_env_only - AttributeError: 'modu...
ERROR tests/test_config.py::test_tier_roles_resolve - AttributeError: 'module...
ERROR tests/test_config.py::test_dotenv_loads_when_env_unset - AttributeError...
ERROR tests/test_config.py::test_exported_env_beats_dotenv - AttributeError: ...
ERROR tests/test_config.py::test_hearth_config_env_var_wins - AttributeError:...
ERROR tests/test_config.py::test_hearth_config_pointing_at_missing_file_raises
========================= 10 failed, 8 errors in 0.14s =========================
```

The genuine, behavioral failures for the four **new** tests (not import errors):

```
>       assert resolve_config_path(component) == target
E       TypeError: resolve_config_path() takes 0 positional arguments but 1 was given
tests/test_config.py:157: TypeError          # test_resolver_targets_named_component_file[engine] & [chat]

        with pytest.raises(FileNotFoundError, match="chat.yaml"):
E           TypeError: resolve_config_path() takes 0 positional arguments but 1 was given
tests/test_config.py:167: TypeError          # test_missing_component_config_fails_loud

>       assert settings.gateway.host == "0.0.0.0"
E       AttributeError: 'Settings' object has no attribute 'gateway'
pydantic/main.py:1042: AttributeError        # test_engine_config_exposes_gateway_section
```

The retargeted existing tests fail because the `config_yaml` fixture and the
cwd/no-config tests now monkeypatch the new `hearth.config.CONFIG_DIR` seam
(absent pre-impl → `AttributeError`), and `_load_default_persona_prompt` now reads
`config/defaults/engine.yaml` (absent pre-impl → `FileNotFoundError`).

### Post-implementation

(recorded below, after implementation)
</content>
