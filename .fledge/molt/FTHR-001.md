# FTHR-001 molt evidence — Package rename and config foundation

## AC-1

Tests written first in `tests/test_config.py` and `tests/test_app.py`, then run
against the unimplemented code to confirm they fail for the expected reason
(the `hearth` package does not exist yet).

Command:

```
.venv/bin/python -m pytest tests/ -v
```

Pre-implementation output (captured verbatim):

```
============================= test session starts ==============================
platform linux -- Python 3.12.13, pytest-9.1.1, pluggy-1.6.0 -- /home/penguin/source/hearth/.fledge/burrows/FTHR-001/.venv/bin/python
cachedir: .pytest_cache
rootdir: /home/penguin/source/hearth/.fledge/burrows/FTHR-001
configfile: pyproject.toml
plugins: asyncio-1.4.0
asyncio: mode=Mode.AUTO, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collecting ... collected 0 items / 2 errors

==================================== ERRORS ====================================
______________________ ERROR collecting tests/test_app.py ______________________
ImportError while importing test module '/home/penguin/source/hearth/.fledge/burrows/FTHR-001/tests/test_app.py'.
Hint: make sure your test modules/packages have valid Python names.
Traceback:
/home/penguin/.pyenv/versions/3.12.13/lib/python3.12/importlib/__init__.py:90: in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
tests/test_app.py:2: in <module>
    from hearth import __version__
E   ModuleNotFoundError: No module named 'hearth'
____________________ ERROR collecting tests/test_config.py _____________________
ImportError while importing test module '/home/penguin/source/hearth/.fledge/burrows/FTHR-001/tests/test_config.py'.
Hint: make sure your test modules/packages have valid Python names.
Traceback:
/home/penguin/.pyenv/versions/3.12.13/lib/python3.12/importlib/__init__.py:90: in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
tests/test_config.py:6: in <module>
    from hearth.config import Settings
E   ModuleNotFoundError: No module named 'hearth'
=========================== short test summary info ============================
ERROR tests/test_app.py
ERROR tests/test_config.py
!!!!!!!!!!!!!!!!!!! Interrupted: 2 errors during collection !!!!!!!!!!!!!!!!!!!!
============================== 2 errors in 0.07s ===============================
```

Fails for the expected reason: the `hearth` package doesn't exist yet (repo is
mid-restart, per CLAUDE.md).

Post-implementation run, same command:

```
============================= test session starts ==============================
platform linux -- Python 3.12.13, pytest-9.1.1, pluggy-1.6.0 -- .../.venv/bin/python
rootdir: /home/penguin/source/hearth/.fledge/burrows/FTHR-001
configfile: pyproject.toml
plugins: asyncio-1.4.0
asyncio: mode=Mode.AUTO, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collecting ... collected 5 items

tests/test_app.py::test_version_command PASSED                           [ 20%]
tests/test_config.py::test_config_loads_yaml_base PASSED                 [ 40%]
tests/test_config.py::test_env_overrides_yaml PASSED                     [ 60%]
tests/test_config.py::test_secret_from_env_only PASSED                   [ 80%]
tests/test_config.py::test_tier_roles_resolve PASSED                     [100%]

============================== 5 passed in 0.08s ===============================
```

## AC-2

The `hearth` package exists (`hearth/__init__.py`, `hearth/config.py`,
`hearth/app.py`) and `hearth --version` succeeds. `pyproject.toml`
(`[project].name`, `[project.scripts]`, `[tool.setuptools.packages.find]`),
`Makefile`, and `.github/workflows/release.yml` reference `hearth`, not
`assistant`.

Commands and output:

```
$ .venv/bin/pip install -e '.[dev]'
Successfully installed hearth-0.1.0 ...

$ .venv/bin/hearth --version
0.1.0
$ echo "exit=$?"
exit=0

$ .venv/bin/hearth run
hearth run: the daemon lands in FTHR-003
$ echo "exit=$?"
exit=1

$ grep -n "assistant\|personal-assistant\|ASSISTANT_" pyproject.toml Makefile .github/workflows/release.yml
pyproject.toml:4:description = "Offline-first voice personal assistant"
```

Only remaining hit is the free-text package `description` field (prose, not a
package/command/artifact name) — out of the feather's Affected Modules scope
(no renaming of prose descriptions was called for). `[project.scripts]` is
`hearth = "hearth.app:main"`; `Makefile`'s comment and `release.yml`'s binary
path, artifact name, and smoke-test env var (`HEARTH_LOGGING__LEVEL`) all use
`hearth`/`HEARTH_`.

`test_version_command` in `tests/test_app.py` pins this (see AC-1 run above —
passing).

## AC-3

The config schema loads via `pydantic-settings` (`hearth/config.py`) with
precedence: `config.yaml` base -> `HEARTH_*` env -> `.env` (secrets), exposing
the Phase 0 sections (`llm`, `veneer`, `tool`, `agent`, `persona`,
`conversation`, `storage`, `logging`) and the `local`/`remote` backends with
capability flags (`supports_tools`, `supports_streaming`, `context_window`,
`cost_tier`, `enabled`) and tier roles (`tiers.default`, `tiers.tool`).

Pinned by `test_config_loads_yaml_base`, `test_env_overrides_yaml`, and
`test_tier_roles_resolve` in `tests/test_config.py` — see the AC-1 passing run
above (all three PASSED).

Manual confirmation of env-nesting precedence:

```
$ .venv/bin/python -c "
from hearth.config import Settings
s = Settings(_env_file=None)
print(s.llm.backends.keys())
print(s.llm.resolve_tier('default'))
"
dict_keys(['local', 'remote'])
base_url='http://localhost:11434/v1' model='qwen3:14b' api_key_env=None supports_tools=True supports_streaming=True context_window=8192 cost_tier='free' enabled=True
```

## AC-4

No secret field appears on the YAML-facing `LLMBackend` model; the OpenRouter
key resolves only from `HEARTH_LLM__OPENROUTER_API_KEY` via
`LLMBackend.resolve_api_key()`, which reads `os.environ[api_key_env]` at call
time rather than storing the secret as a pydantic field.

Pinned by `test_secret_from_env_only` in `tests/test_config.py` — see the AC-1
passing run above (PASSED). That test asserts `"api_key" not in
LLMBackend.model_fields` and that `resolve_api_key()` returns the value set via
`HEARTH_LLM__OPENROUTER_API_KEY`.

`.env.example` carries only `HEARTH_LLM__OPENROUTER_API_KEY` (the legacy
Tavily/Exa/OpenCode-Zen slots are dropped — not needed by the Phase 0 spine
per the feather's Approach). `config.yaml`/`default-config.yaml` reference the
key only by name (`api_key_env: HEARTH_LLM__OPENROUTER_API_KEY`), never by
value.
