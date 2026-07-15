---
generated: 2026-07-15T22:30:28Z
commit: a8489b1afa55662a54ba66548a2e176584a3f387
agent: fledge-forager
fledge_version: 0.5.4
---

# Entry Points

How to run, build, and interface with hearth — CLIs, exported APIs, and build outputs.

## Running the daemon

- **Package entry point** (`pyproject.toml`): `hearth = hearth.app:main` → installed as the `hearth` CLI.
- `hearth.app:main(argv)` — argparse CLI (`--version`, `run` subcommand) (hearth.md).
- `hearth.app:_run_daemon()` — async startup: load `.env`, build `Settings`, `setup_logging`, wire `Router`/`Loop`/`Veneer`/`EventLog`/`BrainConsult`/`ToolRegistry`, then `Veneer.serve()` (hearth.md).
- Dev install: `pip install -e '.[all]'` (every runtime capability) or `pip install -e '.[dev]'` (pytest/ruff only) (`CLAUDE.md`).

## WebSocket control surface (the "veneer")

- **Server**: `hearth.veneer.server.Veneer(loop, log, config).serve(host, port)` — bound to `127.0.0.1:8765` by default (config-driven `veneer.host`/`veneer.port`), one session per connection (root.md, hearth.md).
- Wire-in: `hearth.veneer.protocol.parse_request(raw) -> Request(turn_id, final_user_transcript)`.
- Wire-out: `answer_message(turn_id, text)`, `done_message(turn_id)`, `error_message(turn_id, message)` — via `hearth.veneer.protocol.serialize(event)`, whitelist-only (see conventions.md).
- **Reference client**: `python -m hearth.veneer.client` — `hearth.veneer.client.run_client(host, port)` (async stdin readline loop) and `hearth.veneer.client.send_turn(websocket, transcript) -> list[dict]` (root.md, hearth.md).

## Core orchestration API (internal, not exposed over the wire)

- `hearth.loop.Loop.run_turn(session_id, turn_id, transcript, emit)` — one full turn: log user input, reconstruct history from `EventLog`, run the ReAct loop on the `default` tier, apply persona restyle, log `final_answer`, return text.
- `hearth.loop.run_react_rounds(brain, messages, tools, dispatch, round_cap, log, session_id, turn_id, emit, label_for)` — shared ReAct engine, used both by the top-level orchestrator and by `BrainConsult`.
- `hearth.brain.router.Router.select(tier_override=None) -> Selection` — resolves which backend answers this round.
- `hearth.brain.router.Router.brain_available() -> bool` — gates whether `consult_brain` is offered as a tool this turn.
- `hearth.tools.consult.BrainConsult(router, tool_registry, log, config, transcript)` — callable `__call__(session_id, turn_id, query, emit)`; the nested-ReAct implementation behind the `consult_brain` tool.
- `hearth.tools.registry.ToolRegistry.specs() -> list[ToolSpec]`, `.dispatch(name, args) -> str`.
- `hearth.tools.wikipedia.wikipedia_search(query, client, endpoint, result_count, max_chars, lang, timeout) -> str`.
- `hearth.memory.log.EventLog(db_path).append(...)`, `.read_session(session_id, limit)`.
- `hearth.memory.reader.EventReader(log).read_since(cursor, limit)`, `.latest_cursor()`.

(all: hearth.md)

## Build & release

- `make release` → `packaging/build.sh` — builds a single-file PyInstaller binary for the **host architecture only** (no cross-compile) at `dist/hearth-$(uname -m)`; run once per target arch (x86_64 + aarch64) (`CLAUDE.md`, packaging.md).
- `make clean` — removes build artifacts.
- CI: `.github/workflows/release.yml` — triggered by `v*` tag push or manual `workflow_dispatch`; matrix over `ubuntu-24.04` (x86_64) / `ubuntu-24.04-arm` (aarch64); runs `packaging/build.sh`, smoke-tests the binary (`--version`, DEBUG-level startup), uploads artifacts, and (tag-triggered only) creates/updates the GitHub Release via `softprops/action-gh-release@v2` with both binaries attached (packaging.md).
- `HEARTH_BUILD_EXTRAS` env var controls which extras get bundled into the binary (default `all`; CI always uses `all` for releases) (packaging.md).

## Wake-word training CLIs (separate from the runtime; run inside `training/.venv-train`)

- `python training/train.py [--config] [--smoke] [--skip-setup] [--n-samples] [--steps] [--fresh] [--fresh-clips]` — trains one model; exports `run_training(cfg, *, skip_setup=False)`.
- `python training/train_batch.py [phrases ...] [--smoke] [--n-samples] [--steps] [--skip-setup]` — trains multiple phrases sequentially (defaults to reading `training/phrases.txt`).
- `python training/manifest.py {upsert,list,regen,select}` — model registry management; `select <slug>` is what points `config.yaml`'s `wake.model_paths` at a trained model (stdlib-only, runnable from repo root).
- `training/bootstrap.sh` — builds the isolated `training/.venv-train` (ROCm torch + livekit-wakeword[train,eval,export]).

(training.md)

## Testing entry points

- `pytest` — full suite, `asyncio_mode=auto`.
- `pytest path/to/test_x.py::test_name` — single test.
- `ruff check .` — lint (line-length 100).
- `MANUAL_SMOKE.md` — manual procedure against **real** Ollama/OpenRouter/Wikipedia (`hearth run` + `python -m hearth.veneer.client`, run by hand, not automated) (root.md).

See `testing.md` for the automated-test breakdown.

## Open Questions

None observed beyond those already logged in `architecture.md` (wake-word runtime integration timing).
