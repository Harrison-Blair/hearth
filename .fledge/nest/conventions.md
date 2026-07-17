---
generated: 2026-07-17T06:36:02Z
commit: 2cf763f017cef0f330f2fb0df7157c947be1113a
agent: fledge-forager
fledge_version: 0.6.7
---

# Conventions

Naming, error-handling, layering, and process conventions observed across the repo, reconciled across scout reports.

## Async-first, everywhere

All I/O and LLM calls are async/await; `hearth.app.main()` wraps the daemon in `asyncio.run()`. Backends (`hearth/brain/*`) implement async `complete()` with no blocking I/O. Tests: `pytest-asyncio` with `asyncio_mode = "auto"` (`pyproject.toml`) — async tests are bare `async def test_*()`, no `@pytest.mark.asyncio` decorator needed.

## Config: YAML for tunables, `.env` for secrets — never mixed

Established by FTHR-015. Non-secret tunables (models, hosts, thresholds) live in `config.yaml`; API keys live only in `.env` (`HEARTH_<SECTION>__<PROVIDER>_API_KEY`, e.g. `HEARTH_LLM__OPENROUTER_API_KEY`). `Settings` (`hearth/config.py`) never defines secret fields. Precedence cascade: init kwargs → `HEARTH_*` env vars (double-underscore nesting, e.g. `HEARTH_LLM__MODEL`) → `.env` secrets → `config.yaml` → file secrets. `resolve_config_path()` searches `HEARTH_CONFIG` env var, then package-adjacent path, then cwd.

## Frozen boundaries between layers

- `Loop` never imports `Router`/`EventLog`/`Veneer` directly for the wire path — only via injected `EventSink` callable and `ToolActivity` events (`hearth/events.py`).
- `hearth/veneer/` never imports `hearth/brain/` — only touches `Loop.run_turn()` and catches `BrainError` for curation.
- The `Brain` protocol (`hearth/brain/base.py`) and its `Message`/`ToolCall`/`ToolSpec` types are explicitly frozen (FTHR-004/FTHR-006 in commit history) — changes there ripple to every call site. `BrainResult` is additive-only (FTHR-013): new fields must be defaulted so existing call sites don't break.
- The veneer wire protocol (`hearth/veneer/protocol.py::serialize()`) is a structural whitelist, not a blocklist: only known fields are copied out; unknown event types raise `TypeError` rather than silently passing extra data through. Same pattern in `curate_error()` for exceptions (only `BrainError.reason` is client-safe).

## Error handling: normalize, then degrade gracefully

- All LLM backend failures funnel through `_OpenAICompatBackend.complete()` → `BrainError(reason, detail)`. `reason` is client-safe; `detail` is internal-only and must never include API keys or Authorization headers (verified by `test_brain_errors.py::test_brain_error_never_leaks_api_key`).
- Callers (`Loop.run_turn`, `BrainConsult.__call__`) catch `BrainError` and degrade to a plain-text observation instead of crashing the turn — the turn always completes.
- Retry policy is narrow and deliberate: only transient `httpx.TransportError` (connection/network blips) is retried, up to `llm.max_retries`. `httpx.TimeoutException` is NOT retried (backend is already slow; retrying burns turn budget). `httpx.HTTPStatusError` is NOT retried (won't change on retry).
- Logging and transcript-writing failures are caught and swallowed everywhere they occur (`Transcript.append()` catches `OSError`; `BrainConsult` wraps logger/transcript calls in try/except) — a log or transcript error must never break a turn (AC-5 pattern, referenced in both `hearth-core.md` and `hearth-memory-tools.md`).

## Metrics: in-place mutation for partial-failure tracking

`ReactRoundsMetrics` is passed into `run_react_rounds()` and mutated in place, so partial metrics survive a `BrainError` that's caught and handled by the caller. `BrainConsult.last_metrics` follows the same side-attribute pattern — set upfront, mutated during the call, read by the orchestrator after await.

## Naming and structure

- Tier roles (`"default"`, `"tool"`) are plain strings, not enums, hardcoded into `Router._BACKEND_CLASS_FOR_TIER`.
- Private shared-implementation base classes use a leading underscore (`_OpenAICompatBackend`), with public thin subclasses (`LocalBackend`, `RemoteBackend`).
- Config field nesting for env overrides uses double underscore: `HEARTH_LLM__MODEL`, `HEARTH_VENEER__HOST`.
- Domain-driven module organization: `brain/`, `veneer/`, `memory/`, `tools/`, plus top-level `config.py`, `loop.py`, `app.py`.
- Test helper/double naming: leading underscore for private test doubles (`_FakeLoop`, `_FakeRegistry`, `_FakeWebSocket`, `_Config`, `_make_router`); explicit, descriptive test names (`test_system_prompt_is_first_message`).

## Logging

- `setup_logging()` is idempotent (guards against duplicate handler stacking via a marker attribute on the root logger) and is never called at import time — so importing modules for tests carries no logging side effects.
- Log lines carry `extra={"category": "..."}` for `ColorFormatter` dispatch (`connection` cyan, `server` magenta, `metrics` green/blue per-segment, unknown categories fall back to plain).
- `NO_COLOR` env var and non-TTY output auto-suppress ANSI coloring.

## Linting, formatting, versioning

- `ruff check .`, line-length 100 (`pyproject.toml`).
- Python pinned to 3.12 (`.python-version` says 3.12.13; `pyproject.toml` requires `>=3.11`).
- `dev` extra: `pytest`, `pytest-asyncio`, `ruff` — explicitly excluded from the `all` extra.

## fledge development workflow

- Commit taxonomy: `PLM-xxx` (plumage/epic), `FTHR-xxx` (feather/work unit) with numbered acceptance criteria (AC-1, AC-2, …); `FTHR-xxx: fledged` marks completion; `review: verify FTHR-xxx AC-1..N` / `review: uncheck AC-N` record reviewer passes.
- Test-first discipline (per root `CLAUDE.md`): a new test must be shown failing before the fix/feature lands; tests only count if they fail when the behavior breaks.
- `tests/test_e2e_veneer.py` is the hermetic end-to-end proof of the whole spine; `MANUAL_SMOKE.md` is the companion manual procedure against real Ollama/OpenRouter/Wikipedia services, explicitly designed to separate environment issues from spine bugs.

## Build & release

- `make release` → `packaging/build.sh` → PyInstaller `--onefile`, native per-architecture (x86_64, aarch64; no cross-compile), output `dist/hearth-$(uname -m)`. Builds in an isolated temporary `.build-venv`. `config.yaml` is bundled into the frozen binary root via `--add-data`. `HEARTH_BUILD_EXTRAS` env var controls which optional extras are included (default: `all`).
- CI (`.github/workflows/release.yml`) triggers on `v*` tag pushes or manual dispatch, builds both architectures natively on their own runners, smoke-tests each binary (`--version` + a DEBUG startup run), and attaches artifacts to the GitHub Release.

## Training pipeline isolation (a convention worth preserving)

`training/` is deliberately isolated from the runtime: its own `.venv-train` (ROCm PyTorch + livekit-wakeword), never shared with the runtime venv. `training/manifest.py` is stdlib-only (json, re, pathlib, argparse, yaml) with zero `hearth` runtime imports, keeping it fork-safe and independently runnable. This pattern — a subsystem that produces artifacts for the runtime without the runtime (or vice versa) importing across the boundary — is the same shape as the brain/veneer isolation and worth matching for any new audio subsystem.
