---
generated: 2026-07-17T06:36:02Z
commit: 2cf763f017cef0f330f2fb0df7157c947be1113a
agent: fledge-forager
fledge_version: 0.6.7
---

# Entry Points

How to run, build, and interface with hearth: CLI, config loading, the veneer wire protocol, and the training-pipeline CLIs.

## CLI entry point

`hearth = hearth.app:main` (declared in `pyproject.toml`). `hearth.app.main(argv: list[str] | None = None) -> int` parses `--version` and the `run` subcommand; `run` dispatches to the async `_run_daemon()`.

```bash
pip install -e '.[all]'      # every wired runtime capability
pip install -e '.[dev]'      # pytest, pytest-asyncio, ruff

hearth run                   # start the daemon (foreground; no evidence of daemonization/forking found)
hearth --version
```

`_run_daemon()` loads `.env`, instantiates `Settings`, wires the full object graph (see `architecture.md`), starts `Veneer.serve()`, and runs until cancelled.

## Config loading

`Settings` (`hearth/config.py`) loads via `pydantic-settings`, precedence: init kwargs → `HEARTH_*` env vars (`__` for nesting, e.g. `HEARTH_LLM__MODEL`, `HEARTH_LOGGING__LEVEL`) → `.env` secrets → `config.yaml` → file secrets. `resolve_config_path()` searches, in order: `$HEARTH_CONFIG` env var, a path next to the installed package, then the current working directory. The daemon refuses to start without a resolvable config file.

- `config.yaml` — the active config the daemon loads.
- `default-config.yaml` — reference/defaults with an inline comment per field; read this to understand what a knob does.
- `.env` (gitignored; template at `.env.example`) — **secrets only**, `HEARTH_<SECTION>__<PROVIDER>_API_KEY` format (currently `HEARTH_LLM__OPENROUTER_API_KEY`). Never put secrets in the YAML files.

## Veneer WebSocket control surface (client-facing entry point)

Binds to `config.veneer.host`/`config.veneer.port` (default `127.0.0.1:8765`). One session per WebSocket connection; one turn processed at a time per connection.

**Inbound frame** (raw JSON): `{"turn_id": "<str>", "final_user_transcript": "<str>"}`, parsed by `hearth/veneer/protocol.py::parse_request()` into a `Request`.

**Outbound messages**, emitted in order per turn:
1. Zero or more `{"type": "tool_activity", "turn_id", "phase", "label"}`.
2. One `{"type": "answer", "turn_id", "text"}`.
3. One `{"type": "done", "turn_id"}`.
- On error: one `{"type": "error", "turn_id", "message"}` instead of steps 2–3; connection stays open for the next turn.

**Dev/test client** — `python -m hearth.veneer.client`: minimal stdin/stdout loop; loads `Settings`, calls `run_client(host, port)`, which prompts stdin, calls `send_turn(websocket, transcript)`, and prints the response stream. `send_turn()` is also reused directly by integration tests.

No ping keepalive (`ping_interval=None`) — deliberate, since this is a localhost control surface that legitimately idles between turns.

## Build / release entry points

```bash
make release      # -> packaging/build.sh: single-file binary for the HOST arch only
                   #    output: dist/hearth-$(uname -m). No cross-compile;
                   #    run once per target arch (x86_64 + aarch64).
make clean
```

`packaging/build.sh` creates an isolated `.build-venv`, installs deps fresh, runs PyInstaller `--onefile` with `--collect-submodules hearth` and `--add-data "$(pwd)/config.yaml:."` (bundles the active config into the frozen binary root). `HEARTH_BUILD_EXTRAS` env var controls which extras are included (default `all`). `packaging/entry.py` is the PyInstaller analysis root — it just imports and calls `hearth.app:main`, distinct from the setuptools console-script entry point.

Releases are cut by pushing a `v*` git tag (or manual `workflow_dispatch`); `.github/workflows/release.yml` builds natively on `ubuntu-24.04` (x86_64) and `ubuntu-24.04-arm` (aarch64), smoke-tests each binary (`"$BIN" --version` and a DEBUG-level startup run), and attaches both to the GitHub Release.

## Wake-word training CLIs (separate `.venv-train`, not part of the runtime)

```bash
bash training/bootstrap.sh                                            # one-time .venv-train setup (ROCm PyTorch + livekit-wakeword)

training/.venv-train/bin/python training/train.py --config training/vesta.yaml [--smoke] [--skip-setup] [--fresh] [--fresh-clips] [--n-samples N] [--steps N]
                                                                        # single-model pipeline: generate -> augment -> train -> export -> eval

training/.venv-train/bin/python training/train_batch.py [phrase ...] [--smoke] [--skip-setup] [--n-samples N] [--steps N]
                                                                        # batch trainer; reads training/phrases.txt if no positional args

python training/manifest.py list                                      # show trained models: slug, phrase, recall%, FPPH, threshold (repo-root venv, stdlib-only)
python training/manifest.py select <slug-or-phrase> [...]              # writes wake.model_paths into config.yaml and sets wake.threshold
python training/manifest.py upsert <slug> --phrase "X" --eval <eval.json> [--target-fpph 0.1]   # used internally by train.py
python training/manifest.py regen                                      # backfill manifest for orphaned .onnx files
python training/manifest.py remove <slug>                              # drop a manifest entry
```

`manifest.py` is stdlib-only (no `hearth` runtime imports), so it runs in the repo-root venv without `.venv-train`. `select` is the integration point where a trained model becomes runtime-relevant — but note the `wake.*` config keys it writes do not yet exist in `Settings` (`hearth/config.py` has no `wake` section today).

## Tests

```bash
pytest                        # asyncio_mode=auto — async tests need no decorator
pytest path/to/test_x.py::test_name
ruff check .                  # line-length 100
pytest training/test_manifest.py   # stdlib-only, no .venv-train needed
```

In git worktrees, use `python -m pytest` from the worktree root rather than `.venv/bin/pytest`, or tests run against `main`'s code (see project memory).

## Open Questions

- Does `hearth run` daemonize (fork to background) or run foreground-only? No evidence of forking found in `app.py`.
- What additional CLI subcommands exist beyond `run` and `--version`?
