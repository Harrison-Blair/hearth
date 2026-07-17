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

Command:

```
python -m pytest tests/test_config.py
```

Output:

```
collected 18 items
tests/test_config.py ..................                                  [100%]
============================== 18 passed in 0.05s ==============================
```

The four new tests now pass: `test_resolver_targets_named_component_file[engine]`,
`test_resolver_targets_named_component_file[chat]`,
`test_missing_component_config_fails_loud`, and
`test_engine_config_exposes_gateway_section`; all retargeted existing tests pass.

## AC-2

`config.yaml` moved to `config/engine.yaml` and `default-config.yaml` to
`config/defaults/engine.yaml`, both via `git mv`; no config file remains at the
repo root.

```
$ git diff --name-status main...HEAD
A       .fledge/molt/FTHR-022.md
R092    default-config.yaml     config/defaults/engine.yaml
R098    config.yaml             config/engine.yaml
M       hearth/config.py
M       packaging/build.sh
M       tests/test_config.py

$ ls config.yaml default-config.yaml
ls: cannot access 'config.yaml': No such file or directory
ls: cannot access 'default-config.yaml': No such file or directory

$ git ls-files config/
config/defaults/engine.yaml
config/engine.yaml
```

`R092`/`R098` confirm git tracked both as renames (history follows). `.gitignore`
needed no change — the root `config.yaml` was never ignored, and `config/` is not
excluded.

## AC-3

`resolve_config_path(component: str)` is one facility that derives its target
filename from the component (`config/<component>.yaml`).
`test_resolver_targets_named_component_file` is parameterized over two component
names (`engine`, `chat`) and asserts each resolves its own file, proving the
filename is a variable, not a per-component branch. The engine's `Settings`
calls `resolve_config_path("engine")`; a second caller (the chat veneer, FTHR-024)
passes its own component name — no second loader.

## AC-4

Resolution order is unchanged in substance from the original docstring:
`HEARTH_CONFIG` env var → package-adjacent `config/<component>.yaml` → cwd
`./config/<component>.yaml` → `FileNotFoundError`. The error names both searched
paths and the reference file to copy. `test_missing_component_config_fails_loud`
covers a missing component config raising `FileNotFoundError` naming the searched
path (`chat.yaml`); `test_no_config_anywhere_fails_loud` (existing) covers the
engine's fail-loud path and the reference (`config/defaults/engine.yaml`).
`test_hearth_config_*` (existing) still pin the env-var precedence and its
missing-file error.

## AC-5

`config/engine.yaml` and `config/defaults/engine.yaml` both carry a `gateway:`
section with `host` and `port`, loadable as `settings.gateway`
(`GatewayConfig` on `Settings`). `test_engine_config_exposes_gateway_section`
loads distinct values (`0.0.0.0`/`9999`) from the file to prove file-load, not
model defaults. The `veneer:` section is still present and unchanged in both
files (`grep` shows `veneer:` at engine.yaml:26 and defaults:41).

```
config/defaults/engine.yaml:41:veneer:
config/defaults/engine.yaml:45:gateway:
config/engine.yaml:26:veneer:
config/engine.yaml:29:gateway:
```

## AC-6

`make release` built `dist/hearth-x86_64` (exit 0). The frozen binary was then run
from a fresh temp directory that contains **no** `config/` directory, so config can
only resolve from the bundled `config/engine.yaml` landed by
`--add-data "$(pwd)/config/engine.yaml:config"`.

Negative control — `HEARTH_CONFIG` pointed at a missing file fails loud through the
shared resolver (proves the run path actually loads config, not a silent empty
load):

```
$ HEARTH_CONFIG="$WORK/nope.yaml" dist/hearth-x86_64 run
...
  File "hearth/config.py", line 181, in settings_customise_sources
  File "hearth/config.py", line 44, in resolve_config_path
FileNotFoundError: HEARTH_CONFIG points to a missing file: /tmp/.../nope.yaml
[PYI-...:ERROR] Failed to execute script 'entry' due to unhandled exception!
```

Positive — from a temp cwd with no `config/`, no env override, the daemon starts and
binds (config resolved from the frozen bundle; no `FileNotFoundError`):

```
$ cd "$(mktemp -d)" && timeout 6 dist/hearth-x86_64 run
2026-... │ INFO │ hearth daemon starting
2026-... │ INFO │ veneer serving host=127.0.0.1 port=8765
2026-... │ INFO │ server listening on 127.0.0.1:8765
$ ls logs/            # ./logs written per resolved config
hearth.log
```

`hearth --version` also prints `0.1.0`. Frozen bundle proven to resolve its config
outside the source tree.

## AC-7

No secret-bearing field was added to either YAML. The only secret-adjacent keys are
the pre-existing `api_key_env` entries, which hold the *name* of an env var, never a
value (FTHR-015 rule). This feather's only YAML additions are the non-secret
`gateway.host`/`gateway.port`.

```
$ grep -ni "api_key\|secret\|password\|token" config/engine.yaml config/defaults/engine.yaml
config/engine.yaml:6:      api_key_env: null
config/engine.yaml:15:      api_key_env: HEARTH_LLM__OPENROUTER_API_KEY
config/defaults/engine.yaml:20:      api_key_env: null
config/defaults/engine.yaml:29:      api_key_env: "HEARTH_LLM__OPENROUTER_API_KEY"
```

## AC-8

`hearth/app.py`, `hearth/veneer/**`, and `tests/test_veneer*.py` are untouched — the
`git diff --name-status main...HEAD` under AC-2 lists only `hearth/config.py`,
`packaging/build.sh`, `tests/test_config.py`, the two moved YAML files, and the molt
file. No `veneer:`→`gateway:` rename and no removal of the `veneer:` section.

## AC-9

`ruff check .` is clean and the full existing suite passes.

```
$ ruff check .
All checks passed!

$ python -m pytest
============================= 113 passed in 1.05s ==============================
```
</content>
