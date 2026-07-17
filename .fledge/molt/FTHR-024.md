# FTHR-024 molt evidence — Chat veneer as a standalone process

Worktree: `/tmp/claude-1000/-home-penguin-source-hearth/69bd3e55-6685-474d-a6a3-120622bc7c54/scratchpad/FTHR-024`
Branch: `feather/FTHR-024-chat-veneer-standalone`

Test runs use the shared venv's interpreter with `-m` from the worktree root so
the worktree's `hearth` shadows the editable install:
`/home/penguin/source/hearth/.venv/bin/python -m pytest` (per the worktree
pytest/editable-install note).

## AC-1

The listed tests were written first and observed FAILING against unchanged code
for the expected reasons, then PASS after implementation.

### Pre-implementation failing run (verbatim)

Command:

```
/home/penguin/source/hearth/.venv/bin/python -m pytest \
  tests/test_chat_contract.py tests/test_chat.py \
  tests/test_config.py::test_veneer_config_section_is_gone \
  tests/test_app.py::test_engine_binds_via_gateway_config \
  tests/test_gateway.py::test_no_component_named_veneer -q
```

Output (key assertions / errors, verbatim):

```
E       ModuleNotFoundError: No module named 'hearth.veneers'
tests/test_chat_contract.py:29: ModuleNotFoundError
E       ModuleNotFoundError: No module named 'hearth.veneers'
tests/test_chat.py:40: ModuleNotFoundError          # test_chat_fails_fast_on_unreachable_engine
E       ModuleNotFoundError: No module named 'hearth.veneers'
tests/test_chat.py:64: ModuleNotFoundError          # test_chat_loads_only_its_own_config
>       assert not hasattr(settings, "veneer")
E       AssertionError: assert not True              # test_veneer_config_section_is_gone
tests/test_config.py:176: AssertionError
>       assert captured["host"] == "0.0.0.0"
E       AssertionError: assert '127.0.0.1' == '0.0.0.0'   # test_engine_binds_via_gateway_config
tests/test_app.py:109: AssertionError
>       assert not (pkg_root / "veneer").exists()
E       AssertionError: assert not True              # test_no_component_named_veneer
tests/test_gateway.py:81: AssertionError

6 failed in 0.09s
```

Each failure matches the spec's stated "Fails before" reason:
- contract test / chat tests: the `hearth.veneers` package does not exist yet.
- `test_veneer_config_section_is_gone`: `Settings` still carries a `veneer` field.
- `test_engine_binds_via_gateway_config`: `app.py` serves on `settings.veneer.*`
  (host `127.0.0.1`), so the gateway-host override is ignored.
- `test_no_component_named_veneer`: `hearth/veneer/` still exists.

The spec's fail-fast test names "websockets.connect raises unhandled" as the gap
FC-13 closes. Demonstrated directly against the pre-implementation client
(`hearth/veneer/client.py`) pointed at a closed port:

```
$ python -c "import asyncio, socket; from hearth.veneer.client import run_client; \
  s=socket.socket(); s.bind(('127.0.0.1',0)); p=s.getsockname()[1]; s.close(); \
  asyncio.run(run_client('127.0.0.1', p))"
  ...
  File ".../asyncio/selector_events.py", line 687, in _sock_connect_cb
    raise OSError(err, f'Connect call failed {address}')
ConnectionRefusedError: [Errno 111] Connect call failed ('127.0.0.1', 51071)
EXIT=1
```

An unhandled traceback — exactly what `base.connect`'s `EngineUnreachable`
replaces with a plain message.

### Post-implementation passing run (verbatim)

```
$ .../python -m pytest tests/test_chat_contract.py tests/test_chat.py \
    tests/test_config.py::test_veneer_config_section_is_gone \
    tests/test_app.py::test_engine_binds_via_gateway_config \
    tests/test_gateway.py::test_no_component_named_veneer tests/test_chat_client.py -q
........                                                                 [100%]
8 passed in 0.20s
```

## AC-2

`tests/test_chat_contract.py::test_chat_reaches_engine_only_over_the_wire` walks
every `*.py` under `hearth/veneers/` (AST parse) and asserts none import
`hearth.brain`, `hearth.loop`, `hearth.memory`, or `hearth.gateway`. Written over
the `hearth.veneers` package root (`root.rglob("*.py")`), not `chat` specifically,
so any future surface is covered the day its file is added. Passes (see AC-1
post-run). Satisfies PLM-007 FC-1.

## AC-3

`chat` reproduces today's console behavior. The rendering code moved verbatim
from `hearth/veneer/client.py` into `hearth/veneers/chat/__main__.py`
(`_print_message`, `_read_line`, `run_client`, git-mv so history follows):
`> ` prompt, `…{label}` tool activity, red `[hearth]` answer tag
(`\033[31mhearth\033[0m`), `error: …` display, and the non-blocking
`asyncio.to_thread(sys.stdin.readline)`. The keepalive regression test survives
the move (`tests/test_chat_client.py::test_read_line_does_not_block_event_loop`,
renamed from `test_veneer_client.py`). Manually observed in AC-4: the live turn
rendered `> [<red>hearth</red>] 2 plus 2 equals 4.`.

## AC-4

Manual smoke against an **installed console script** and a **running engine**,
run in an isolated venv (`/tmp/fthr024-smoke`, `pip install -e .`) to avoid
disturbing the shared editable install. Ollama (`qwen3:14b`) was live, so the
local `default` tier answered a plain turn without the remote brain.

Real turn against a running engine:

```
$ /tmp/fthr024-smoke/bin/hearth run &        # engine, bound 127.0.0.1:8765
$ printf 'what is 2 plus 2\n' | /tmp/fthr024-smoke/bin/hearth-chat
EXIT=0
> [^[[31mhearth^[[0m] 2 plus 2 equals 4.
>
```

(`cat -v` shows the red-tag escape codes `^[[31m … ^[[0m` around `hearth`.)

Engine stopped, rerun:

```
$ printf 'hello\n' | /tmp/fthr024-smoke/bin/hearth-chat
EXIT=1
--- STDERR ---
cannot reach the hearth engine at 127.0.0.1:8765 -- is it running? start it with `hearth run`.
--- traceback count --- 0
```

A plain message naming host `127.0.0.1` and port `8765`, non-zero exit (`1`), no
traceback. Procedure recorded in `MANUAL_SMOKE.md` §3. Satisfies PLM-007 FC-3,
FC-13.

## AC-5

Chat reads only `config/chat.yaml`, via FTHR-022's shared facility, as its second
caller. `hearth/veneers/chat/config.py::ChatSettings.settings_customise_sources`
calls `resolve_config_path("chat")` — the same facility the engine calls with
`"engine"`. `tests/test_chat.py::test_chat_loads_only_its_own_config` loads chat
from a config dir containing ONLY `chat.yaml` and asserts `engine.host`/`.port`
read correctly while the engine's `Settings(_env_file=None)` raises
`FileNotFoundError` (its config genuinely absent) — the two are independent.
`ChatSettings` imports `resolve_config_path` from `hearth.config`, never the
engine's `Settings`. Satisfies PLM-007 FC-9, FC-10.

## AC-6

Dual-section transitional state ended, no compatibility alias:
- `VeneerConfig` class and `Settings.veneer` field removed from `hearth/config.py`.
- `veneer:` section removed from `config/engine.yaml` and
  `config/defaults/engine.yaml`.
- `hearth/app.py` binds via `settings.gateway.host/.port` (log line and
  `gateway.serve(...)`); `hearth/gateway/server.py`'s `serve()` fallback also
  repointed `self._config.veneer.*` → `self._config.gateway.*`.
- `hearth/veneer/` deleted.
- `tests/test_config.py::test_veneer_config_section_is_gone` asserts no `veneer`
  attribute on `Settings`, `"veneer" not in Settings.model_fields`, and that
  `HEARTH_VENEER__PORT` influences nothing (gateway unaffected).
- `tests/test_app.py::test_engine_binds_via_gateway_config` asserts the daemon
  serves on `settings.gateway.*` and ignores the dead `HEARTH_VENEER__*`.
Satisfies PLM-007 FC-11, FC-12.

## AC-7

`tests/test_gateway.py::test_no_component_named_veneer` (tightened/renamed from
FTHR-023's `test_no_engine_side_component_named_veneer`) asserts
`(pkg_root / "veneer").exists()` is False and `(pkg_root / "veneers").is_dir()`
is True — nothing under `hearth/` is named veneer except `hearth/veneers/`.
Passes.

## AC-8

`hearth/veneers/base.py` contains only what `chat` uses: `EngineUnreachable`,
an `async` `connect(host, port)` context manager (fail-fast), and `send_turn`.
No speculative hooks for the unbuilt audio surfaces, and no retry — retry is
PLM-008 FC-10's, deliberately asymmetric (audio is unattended; chat is at a
terminal). The module docstring records this.

## AC-9

`tests/test_chat_contract.py` additionally asserts the only `hearth` imports in
the veneers tree are `hearth.config` (the facility) and `hearth.veneers.*` —
everything else is stdlib or `websockets`. `base.py` imports `json`, `uuid`,
`contextlib`, `websockets`; `chat/__main__.py` imports `asyncio`, `sys`, and the
veneers tree; `chat/config.py` imports pydantic + `hearth.config`. Passes.

## AC-10

```
$ .../python -m pytest -q
119 passed in 1.05s
$ .../python -m ruff check .
All checks passed!
```
