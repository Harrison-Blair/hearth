---
id: FTHR-019
title: Server category tagging
plumage: PLM-004
status: fledged
priority: P2
depends_on: [FTHR-016]
authored: 2026-07-16T00:28:15Z
agent: fledge-orchestrate/planning
fledge_version: 0.5.5
---

# FTHR-019: Server category tagging

## Description
Give the daemon's startup/lifecycle a `server` category so FTHR-016's
console formatter colors it distinctly. `hearth/app.py::_run_daemon()`
currently has no logger calls at all (only `print(__version__)` for the
unrelated `--version` flag). This feather adds a small number of minimal
`logger.info(...)` lines marking daemon lifecycle points and tags them with
`extra={"category": "server"}`. Depends only on FTHR-016 (the
formatter/registry).

## Affected Modules
- `hearth/app.py` — `_run_daemon()` (see `.fledge/nest/entry-points.md` →
  "Run" / "Daemon": `hearth run` → `_run_daemon()` loads `.env`,
  instantiates `Settings`, wires `Router`/`EventLog`/`ToolRegistry`/`Loop`/
  `Veneer`, calls `veneer.serve(host, port)`). A module-level
  `logger = logging.getLogger(__name__)` needs to be added here since none
  exists today (`hearth/app.py` currently imports nothing from `logging`).
- `hearth/logging_setup.py` — register the `server` category's coloring
  rule in FTHR-016's registry.

## Approach
1. Add `import logging` and `logger = logging.getLogger(__name__)` at
   module level in `hearth/app.py` (matching the pattern already used in
   `hearth/loop.py`, `hearth/tools/consult.py`, `hearth/veneer/server.py`).
2. In `_run_daemon()`, add two minimal INFO log lines, each tagged
   `extra={"category": "server"}`:
   - Right after `setup_logging(settings.logging)` runs (logging is now
     configured, so this is the earliest point a log line will actually be
     captured): `logger.info("hearth daemon starting")`.
   - Right before `await veneer.serve(...)`: `logger.info("veneer serving
     host=%s port=%s", settings.veneer.host, settings.veneer.port,
     extra={"category": "server"})`.
   Keep both lines minimal and purely observational — no behavior change to
   `_run_daemon()`'s control flow, object wiring, or the `finally` client-
   cleanup block.
3. In `hearth/logging_setup.py`, register a `"server"` entry in FTHR-016's
   category registry (a coloring treatment distinct from
   `metrics`/`connection`/plain, never reusing the ERROR/CRITICAL color).
4. No changes to `main()`, argument parsing, or the `--version` path (its
   `print()` stays untouched — this feather only affects the `run`
   subcommand's daemon startup).

## Tests
Written test-first — run against the code as it stands after FTHR-016
(before this feather's changes) and confirm failure (no logger exists in
`app.py` yet; no `server`-category records are emitted), then implement
until passing. Lands in `tests/test_app.py` (existing file, reuses its
`_run_daemon()`-with-a-fake-`Veneer` pattern already used by
`test_run_daemon_wires_wikipedia_tool_brain_side`).
- `test_run_daemon_logs_server_lifecycle_lines`: reuse the existing
  `_FakeVeneer`/`monkeypatch` pattern from `test_run_daemon_wires_wikipedia_tool_brain_side`
  to run `_run_daemon()` against a fake `Veneer` (so it returns immediately
  instead of blocking on `asyncio.Future()`), and assert via `caplog` that
  both the "daemon starting" and "veneer serving" lines are emitted with
  `record.category == "server"`.
- `test_server_category_gets_registered_coloring` (extends
  `test_console_formatter.py`/`test_logging.py`): format a server-shaped
  log record with `category="server"` through the console formatter (color
  forced on) and assert it renders distinctly from `metrics`/`connection`/
  plain and never the reserved ERROR/CRITICAL color.
- Regression check: `test_version_command` and the existing
  `test_run_daemon_wires_wikipedia_tool_brain_side` assertions pass
  unmodified — this feather only adds log lines, no change to `_run_daemon`'s
  return value or object wiring.

## Acceptance Criteria
- [x] AC-1: The tests listed above were observed failing before implementation and pass after.
- [x] AC-2: `_run_daemon()` emits an INFO "daemon starting" line and an INFO "veneer serving host=.../port=..." line, both tagged `extra={"category": "server"}`, with no change to `_run_daemon`'s control flow or return value. Satisfies PLM-004 FC-6.
- [x] AC-3: The console formatter's `server` category renders these lines distinctly from `metrics`/`connection`/plain and never reuses the reserved ERROR/CRITICAL color, completing PLM-004 AC-3's server-category coverage.
- [x] AC-4: Existing `test_app.py` tests (`test_version_command`, `test_run_daemon_wires_wikipedia_tool_brain_side`) pass unmodified.
