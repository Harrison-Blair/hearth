# FTHR-023 molt evidence — Engine gateway rename

Pure engine-side rename (veneer → gateway). Behavior identical: no change to the
wire format, `protocol.serialize`'s whitelist, session handling, or
`ping_interval=None`.

Test runner: main repo venv python, invoked from the worktree root so `import
hearth` resolves to the worktree tree (worktree has no local `.venv`):
`/home/penguin/source/hearth/.venv/bin/python -m pytest` run from
`.../scratchpad/FTHR-023`.

## AC-1

The two tests that genuinely fail first are the new
`test_no_engine_side_component_named_veneer` (added to `tests/test_veneer.py`,
carried into `tests/test_gateway.py` by `git mv`) and the retargeted
`"gateway serving"` log assertion in
`tests/test_app.py::test_run_daemon_logs_server_lifecycle_lines`.

### Pre-implementation — observed FAILING for the expected reason

Command:

```
python -m pytest tests/test_veneer.py::test_no_engine_side_component_named_veneer \
  tests/test_app.py::test_run_daemon_logs_server_lifecycle_lines -q
```

Output (verbatim):

```
FF                                                                       [100%]
=================================== FAILURES ===================================
__________________ test_no_engine_side_component_named_veneer __________________
...
        pkg_root = Path(hearth.__file__).parent
>       assert not (pkg_root / "veneer" / "server.py").exists()
E       AssertionError: assert not True
E        +  where True = exists()
E        +    where exists = ((PosixPath('.../FTHR-023/hearth') / 'veneer') / 'server.py').exists

tests/test_veneer.py:82: AssertionError
_________________ test_run_daemon_logs_server_lifecycle_lines __________________
...
        assert any("daemon starting" in m for m in messages)
>       assert any("gateway serving" in m for m in messages)
E       assert False
...
----------------------------- Captured stdout call -----------------------------
2026-07-17 12:51:53,743 │ INFO │ hearth daemon starting
2026-07-17 12:51:53,769 │ INFO │ veneer serving host=127.0.0.1 port=8765
=========================== short test summary info ============================
FAILED tests/test_veneer.py::test_no_engine_side_component_named_veneer - Ass...
FAILED tests/test_app.py::test_run_daemon_logs_server_lifecycle_lines - asser...
2 failed in 0.08s
```

Expected reasons confirmed: `hearth/veneer/server.py` still exists (pre-rename),
and app.py still logs `"veneer serving"` (pre-rename).

### Post-implementation — PASSING

(Recorded after the rename; see the full-suite run under AC-8.)

## AC-2

No engine-side component named "veneer": `hearth/veneer/{server,protocol}.py`
removed, `hearth/gateway/{server,protocol}.py` provide them, class is `Gateway`.
`test_no_engine_side_component_named_veneer` (now in `tests/test_gateway.py`)
asserts exactly this and passes post-rename. Satisfies PLM-007 FC-2.

## AC-3

`git mv` used for both modules and all three test modules so history follows:

```
(git log --follow output recorded below)
```

## AC-4

Behavior unchanged — full existing suite passes with no test's intent altered
(only names/imports/one log string moved). No change to the wire format, the
`protocol.serialize` whitelist, session handling, or `ping_interval=None`. The
malformed-frame provenance literal (`"veneer"` source field, gateway/server.py)
is preserved per AC-4 / FTHR-025.

## AC-5

`grep -rniI veneer` over the repo and full accounting recorded below.

## AC-6

`hearth/logging_setup.py:52` and `tests/test_console_formatter.py:111` updated
to name `hearth/gateway/server.py` (the moved path).

## AC-7

`hearth/config.py`, `config/**`, `packaging/build.sh`, `tests/test_config.py`
untouched — verified below.

## AC-8

`ruff check .` clean and full existing suite green — recorded below.
