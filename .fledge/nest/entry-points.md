---
generated: 2026-07-15T23:27:05Z
commit: e41ba8a73a56364e7c3bb1acf1332cadab817e45
agent: fledge-forager
fledge_version: 0.5.5
---

# Entry Points

How to install, run, build, and release `hearth`, and the public interfaces each module exposes.

## Install

```bash
pip install -e '.[all]'   # every wired runtime capability
pip install -e '.[dev]'   # pytest, pytest-asyncio, ruff
```

## Run

- **Console script:** `hearth = hearth.app:main` (`pyproject.toml [project.scripts]`).
- **CLI:** `main(argv)` → `argparse` (`--version`, `run` subcommand) → `asyncio.run(_run_daemon())`.
- **Daemon:** `hearth run` → `hearth/app.py::_run_daemon()` loads `.env`, instantiates `Settings`, wires `Router` / `EventLog` / `ToolRegistry` / `Loop` / `Veneer`, calls `veneer.serve(host, port)`.
- **Client:** `python -m hearth.veneer.client` — companion CLI that connects to the running daemon's WebSocket, reads stdin on a background thread, prints answers/tool-activity/errors.

## Build / release

```bash
make release   # -> packaging/build.sh: PyInstaller single-file binary, dist/hearth-$(uname -m)
make clean      # -> rm -rf build dist .build-venv
```

- `packaging/build.sh` — `HEARTH_BUILD_EXTRAS` env var (default `all`) controls which extras get baked in; no cross-compilation, run once per target arch.
- `packaging/entry.py` — thin PyInstaller entry point, imports `hearth.app:main`.
- **CI/release:** push a `v*` tag → `.github/workflows/release.yml` builds natively on `ubuntu-24.04` (x86_64) and `ubuntu-24.04-arm` (aarch64), smoke-tests (`--version`, cold start), uploads both binaries to the GitHub Release.
- **Manual smoke test:** `MANUAL_SMOKE.md` — non-hermetic procedure against real Ollama/OpenRouter/Wikipedia, with environment-vs-bug triage guidance.

## Test

```bash
pytest                              # asyncio_mode=auto, all tests
pytest tests/test_loop.py           # one file
pytest tests/test_loop.py::test_x   # one test
pytest -v                           # verbose
ruff check .                        # line-length 100
```

## Public interfaces per module (where execution/data enters)

- **`Loop.run_turn(session_id, turn_id, transcript, emit=null_sink) -> str`** (`hearth/loop.py`) — the turn dispatcher: reconstructs history from `EventLog`, selects the brain via `Router`, runs the shared ReAct engine, logs every phase, appends to transcript. Called once per inbound WebSocket request.
- **`run_react_rounds(brain, messages, tools, dispatch, round_cap, log, session_id, turn_id, emit, label_for) -> BrainResult`** (`hearth/loop.py`) — shared ReAct engine; both the top-level orchestrator turn and the nested `consult_brain` call reuse this, never duplicate it.
- **`ToolRegistry.dispatch(name, args) -> str`** (`hearth/tools/registry.py`) — routes a tool call to its implementation (currently only `wikipedia_search`) or raises `KeyError`.
- **`wikipedia_search(query, client, endpoint, result_count, max_chars, lang, timeout) -> str`** (`hearth/tools/wikipedia.py`).
- **`BrainConsult.__call__(session_id, turn_id, query, emit) -> str`** (`hearth/tools/consult.py`) — nested ReAct over the `tool` tier; degrades `BrainError`/timeout to a plain-text observation.
- **`Veneer.serve(host, port)`** (`hearth/veneer/server.py`) — the WebSocket daemon; `_handle_connection(websocket)` handles one connection, parsing `Request` JSON and sending `answer`/`tool_activity`/`done`/`error` messages.
- **`EventLog.append(session_id, turn_id, type, provenance, payload) -> Event`**, **`read_session(session_id, limit) -> list[Event]`** (`hearth/memory/log.py`) — the only two writer-facing operations; append-only.
- **`EventReader.read_since(cursor, limit) -> list[Event]`**, **`latest_cursor() -> int`** (`hearth/memory/reader.py`) — the read-only Layer-2 seam for a future background indexer.

## Training-pipeline entry points (isolated venv — see `dependencies.md`)

```bash
bash training/bootstrap.sh                                   # one-time .venv-train setup
training/.venv-train/bin/python training/train.py [OPTIONS]  # single-model training
training/.venv-train/bin/python training/train_batch.py      # multi-phrase batch training
python training/manifest.py list|upsert|regen|select ...     # model registry / config.yaml wiring
```

- `train.py` flags: `--smoke`, `--skip-setup`, `--n-samples N`, `--steps N`, `--fresh`, `--fresh-clips`.
- `manifest.py select <refs>` — the step that actually writes `config.yaml`'s `wake.model_paths` (or set `HEARTH_WAKE__MODEL_PATHS` env var equivalently); the model itself is still not consumed anywhere in `hearth/` today.

## Open Questions

- None beyond what's already tracked in `architecture.md` / `dependencies.md`.
