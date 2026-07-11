---
id: FTHR-001
title: Package rename and config foundation
plumage: PLM-001
status: pipping
priority: P0
depends_on: []
oversight: merge
authored: 2026-07-10T23:41:08Z
agent: fledge-orchestrate/planning
fledge_version: 0.3.0
---

# FTHR-001: Package rename and config foundation

## Description
Establish the `hearth` runtime package and its configuration substrate — the root every other Phase 0 feather builds on. Renames the distribution, console command, and entry point from `assistant` to `hearth` (updating `pyproject.toml`, `Makefile`, and CI), and introduces a new `pydantic-settings` configuration schema for the spine, reusing applicable values from the legacy config. Delivers a runnable `hearth --version`; the actual daemon (`hearth run`) is a stub here and is fleshed out in FTHR-003.

## Affected Modules
- `pyproject.toml` — `[project] name`, `[project.scripts]`, `[tool.setuptools.packages.find]` (see `.fledge/nest/dependencies.md`, `.fledge/nest/entry-points.md`).
- `Makefile`, `.github/workflows/release.yml` — artifact/command rename (see `.fledge/nest/entry-points.md` → build/release flow).
- New `hearth/` package: `hearth/__init__.py`, `hearth/config.py`, `hearth/app.py`.
- `config.yaml`, `default-config.yaml`, `.env.example` — new schema + `HEARTH_` secrets (see `.fledge/nest/data-model.md`, `.fledge/nest/conventions.md` → FTHR-015 secrets rule).

## Approach
- **Config models** (`hearth/config.py`): nested `pydantic-settings` `BaseSettings` with `env_prefix="HEARTH_"`, `env_nested_delimiter="__"`, `.env` support, and a **YAML source** (via `settings_customise_sources`) loading `config.yaml` as the base layer. Precedence: YAML base → `HEARTH_*` env → `.env` (secrets). Phase 0 sections: `llm` (backends map + tier roles), `veneer` (host/port), `tool` (wikipedia settings), `agent` (`max_tool_rounds`, `turn_timeout_s`, `tool_mode`), `persona` (`enabled`), `conversation` (`max_history_turns`), `storage` (`db_path`), `logging` (`level`, `dir`).
- **`llm` schema**: a `backends` map with `local` and `remote` entries — each with `base_url`, `model`, `api_key_env` (name of the env var holding the secret, or null), `supports_tools`, `supports_streaming`, `context_window`, `cost_tier`, `enabled` — plus `tiers: {default: local, tool: remote}`, `timeout`, `max_retries`. These field names are the boundary contract FTHR-004 (router) consumes; keep them stable. `supports_streaming` is present but unused in Phase 0.
- **Values reused from legacy** (`.fledge/nest/data-model.md`): local `qwen3:14b` @ `http://localhost:11434/v1`; remote `openrouter/free` (blank `base_url` → OpenRouter default), `api_key_env: HEARTH_LLM__OPENROUTER_API_KEY`, `enabled: true`; `storage.db_path: hearth.db`; `conversation.max_history_turns: 12`; `agent.max_tool_rounds: 3`, `turn_timeout_s: 45`, `tool_mode: auto`; `veneer.host: 127.0.0.1`, `port: 8765`.
- **Config files**: `config.yaml` and `default-config.yaml` are **overwritten in place** with the new Phase 0 schema (git history preserves the old cascade config); `default-config.yaml` carries an inline comment per field per the repo's two-file convention. `.env.example` renamed keys to `HEARTH_LLM__OPENROUTER_API_KEY` (drop the unused legacy secret slots not needed by the spine; keep only OpenRouter).
- **`hearth/app.py`**: `main(argv=None)` handling `--version` (prints the package version, exit 0) and a `run` subcommand that in this feather exits with a clear "the daemon lands in FTHR-003" message. This satisfies CI's smoke test now and is extended by FTHR-003.
- **Packaging**: `pyproject` `name = "hearth"`, `[project.scripts]` `hearth = "hearth.app:main"`, `packages.find` include `["hearth*"]`; `Makefile` output `dist/hearth-$(uname -m)`; `release.yml` smoke `hearth --version` and artifact names `hearth-*`. Do not touch the (absent) `packaging/build.sh` reference beyond the artifact-name rename — recreating it is out of scope.

## Tests
Written test-first (write → observe FAIL for the expected reason → implement to green). In `tests/test_config.py` and `tests/test_app.py`, hermetic (no network), `pytest`/`asyncio_mode=auto`, ruff line-length 100:
- `test_config_loads_yaml_base` — a written `config.yaml` populates the schema (backends, tiers, storage, veneer); pins the YAML source. (AC-3)
- `test_env_overrides_yaml` — `HEARTH_STORAGE__DB_PATH` overrides the YAML value; pins env precedence + `__` nesting. (AC-3)
- `test_secret_from_env_only` — `HEARTH_LLM__OPENROUTER_API_KEY` in env resolves into the effective key, and no secret field is present on the YAML-facing model; pins the FTHR-015 rule. (AC-4)
- `test_tier_roles_resolve` — `tiers.default`/`tiers.tool` resolve to the `local`/`remote` backend configs. (AC-3)
- `test_version_command` — `main(["--version"])` prints the version and exits 0; pins the entry point for CI. (AC-2)

## Acceptance Criteria
- [x] AC-1: The tests listed above were observed failing before implementation and pass after.
- [x] AC-2: The `hearth` package exists and `hearth --version` succeeds; `pyproject.toml`, `Makefile`, and `.github/workflows/release.yml` reference `hearth` not `assistant` (satisfies PLM-001 FC-1, AC-7).
- [x] AC-3: The config schema loads via `pydantic-settings` with YAML → `HEARTH_*` env → `.env` precedence, exposing the Phase 0 sections and the `local`/`remote` backends with their capability flags and tier roles (satisfies PLM-001 FC-2, FC-3, FC-4).
- [x] AC-4: No secret field appears in the YAML-facing schema; the OpenRouter key resolves only from `HEARTH_LLM__OPENROUTER_API_KEY` (satisfies PLM-001 FC-2).
