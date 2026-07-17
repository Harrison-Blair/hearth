# FTHR-023 molt evidence — Engine gateway rename

Pure engine-side rename (veneer → gateway). Behavior identical: no change to the
wire format, `protocol.serialize`'s whitelist, per-connection session handling,
or `ping_interval=None`.

Test runner: main repo venv python, invoked from the worktree root so `import
hearth` resolves to the worktree tree (the worktree has no local `.venv`):
`/home/penguin/source/hearth/.venv/bin/python -m pytest` run from
`.../scratchpad/FTHR-023`. Confirmed `hearth.__file__` resolves under the
worktree.

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

Output (verbatim, abridged tracebacks):

```
FF                                                                       [100%]
=================================== FAILURES ===================================
__________________ test_no_engine_side_component_named_veneer __________________
        pkg_root = Path(hearth.__file__).parent
>       assert not (pkg_root / "veneer" / "server.py").exists()
E       AssertionError: assert not True
E        +  where True = exists()
E        +    where exists = ((PosixPath('.../FTHR-023/hearth') / 'veneer') / 'server.py').exists
tests/test_veneer.py:82: AssertionError
_________________ test_run_daemon_logs_server_lifecycle_lines __________________
        assert any("daemon starting" in m for m in messages)
>       assert any("gateway serving" in m for m in messages)
E       assert False
----------------------------- Captured stdout call -----------------------------
2026-07-17 12:51:53,743 │ INFO │ hearth daemon starting
2026-07-17 12:51:53,769 │ INFO │ veneer serving host=127.0.0.1 port=8765
=========================== short test summary info ============================
FAILED tests/test_veneer.py::test_no_engine_side_component_named_veneer - Ass...
FAILED tests/test_app.py::test_run_daemon_logs_server_lifecycle_lines - asser...
2 failed in 0.08s
```

Expected reasons confirmed: `hearth/veneer/server.py` still existed (pre-rename),
and app.py still logged `"veneer serving"` (pre-rename).

### Post-implementation — PASSING

```
python -m pytest tests/test_gateway.py::test_no_engine_side_component_named_veneer \
  tests/test_app.py::test_run_daemon_logs_server_lifecycle_lines -q
->  2 passed in 0.06s
```

(Both tests are green in the full-suite run under AC-8.)

## AC-2

No engine-side component is named "veneer":

- `hearth/veneer/server.py` and `hearth/veneer/protocol.py` are gone.
- `hearth/gateway/server.py` and `hearth/gateway/protocol.py` provide them
  (plus new empty `hearth/gateway/__init__.py`).
- The class is `Gateway` (was `Veneer`); `hasattr(gateway_server, "Veneer")`
  is False.

`tests/test_gateway.py::test_no_engine_side_component_named_veneer` asserts
exactly this and passes post-rename. Satisfies PLM-007 FC-2. `hearth/veneer/`
still exists containing only `client.py` (+ `__init__.py`) — FTHR-024 removes it.

## AC-3

`git mv` used for both modules and all three test modules; `git log --follow`
traces each new path back through the rename (R…) to its original add (A):

```
hearth/gateway/server.py     : R095 hearth/veneer/server.py -> hearth/gateway/server.py
hearth/gateway/protocol.py   : R096 hearth/veneer/protocol.py -> hearth/gateway/protocol.py
tests/test_gateway.py        : R088 tests/test_veneer.py -> tests/test_gateway.py
tests/test_gateway_errors.py : R087 tests/test_veneer_errors.py -> tests/test_gateway_errors.py
tests/test_e2e_gateway.py    : R095 tests/test_e2e_veneer.py -> tests/test_e2e_gateway.py
```

## AC-4

Behavior unchanged — the full existing suite passes with no test's *intent*
altered (only names, imports, local variable names, and the one log string
moved). Specifically preserved unchanged:

- Wire format / builders in `gateway/protocol.py` (only the module docstring
  changed).
- `protocol.serialize`'s structural whitelist — byte-identical.
- Per-connection session handling and error paths in
  `gateway/server.py::_handle_connection` — unchanged.
- `ping_interval=None` in `Gateway.serve` — unchanged (guarded by
  `test_veneer_client.py::test_serve_disables_keepalive`, still green).
- The malformed-frame provenance literal — the `"veneer"` *source value* at
  `hearth/gateway/server.py:73` (`self._log.append(session_id, "", "error",
  "veneer", ...)`) is a logged value kept as-is per AC-4 / FTHR-025, NOT a
  component name.
- `Gateway.serve` still reads `self._config.veneer.host/.port`; app.py still
  passes `settings.veneer.host/.port` — the config-section rename is FTHR-024's
  and this mismatch is expected/correct at this feather's boundary.

## AC-5

Final `grep -rniI veneer` over the source tree (excluding `.git`, `.venv`,
`__pycache__`, and `.fledge`). `.fledge/**` is hand-authored fledge planning /
context source that intentionally discusses the veneer→gateway transition across
PLM-007 (529 hits) — out of scope for this feather, which never edits spec/nest
docs.

Command: `grep -rniI veneer . --exclude-dir=.git --exclude-dir=.fledge
--exclude-dir=.venv --exclude-dir=__pycache__` → 44 hits, every one accounted:

**(a) `hearth/veneer/client.py` and its test (stays until FTHR-024):**
- `hearth/veneer/client.py:1,64`
- `tests/test_veneer_client.py:1` (docstring), `:15` (`from hearth.veneer import client`)
- `tests/test_gateway.py:12`, `tests/test_e2e_gateway.py:38` —
  `from hearth.veneer.client import send_turn`: the renamed engine tests reuse
  the *client's* `send_turn` helper, which legitimately still lives under
  `hearth.veneer` until FTHR-024. (Client reference, category a.)

**(b) the `veneer:` config section and its readers (section rename is FTHR-024's):**
- `hearth/config.py:85` (`class VeneerConfig`), `:141` (`veneer: VeneerConfig`)
- `config.yaml:26`, `default-config.yaml:40` (`veneer:` block)
- `tests/test_config.py:36,67`
- `hearth/app.py:74,75,78` (`settings.veneer.host/.port` — left as-is per spec)
- `hearth/gateway/server.py:35,36` (`self._config.veneer.host/.port` — the
  Gateway reading a `veneer:` section, expected/correct at this boundary)

**(c) `pyproject.toml:14`** — the "veneer server/client" dependency comment
(FTHR-026 owns it).

**(d) user-facing docs (owned by a later docs feather — NOT fixed here):**
- `README.md:15,42,46,69,146,163,167,190`
- `MANUAL_SMOKE.md:1,4,33,35,56`
- `CLAUDE.md:14,75,98,110`
- NOTE: `README.md:163,167` and `MANUAL_SMOKE.md:4` reference
  `tests/test_e2e_veneer.py`, which this feather renamed to
  `tests/test_e2e_gateway.py` — so those doc references are now stale *paths*.
  Per the spec's explicit ownership model (grep-accounting category d), user-
  facing docs are owned by a named later docs feather and are deliberately NOT
  touched here (contrast AC-6, which fixes only the two *code* comments). Flagged
  for the reviewer as intentional, not an oversight.

**(e) the preserved malformed-frame provenance literal:**
- `hearth/gateway/server.py:73` — `"veneer"` logged source value (AC-4 / FTHR-025).

**(f) the AC-2 completeness test's own semantic references (spec-mandated):**
- `tests/test_gateway.py:70,71,72,73,74,82,83,88` — the function
  `test_no_engine_side_component_named_veneer`, whose whole purpose (named in the
  spec's Tests section) is to assert the *absence* of engine-side `veneer`
  modules; it must name `hearth/veneer/{server,protocol}.py` and the old class
  `Veneer` to check they are gone. These references are the assertion itself.

No unaccounted hit remains. (Comments the spec assigned to this feather —
`hearth/events.py:1,4`, `hearth/logging_setup.py:52`,
`tests/test_console_formatter.py:111` — were fixed and so no longer appear.)

## AC-6

Both stale path comments now name the moved file `hearth/gateway/server.py`:

- `hearth/logging_setup.py:52`
- `tests/test_console_formatter.py:111`

(Also fixed, per the spec's Tests section as "comment edits, safe under AC-4":
`hearth/events.py:1,4` — the "loop -> gateway emit path" / "FTHR-003's gateway
supplies a sink" comments.)

## AC-7

`hearth/config.py`, `config/**`, `packaging/build.sh`, and `tests/test_config.py`
are untouched by this feather — FTHR-022 runs concurrently on them.

```
git diff --stat HEAD~2 -- hearth/config.py 'config/**' packaging/build.sh tests/test_config.py
->  (empty — no changes)
```

(`HEAD~2` = the branch point before the test-first and rename commits.)

## AC-8

```
ruff check .   ->  All checks passed!
python -m pytest -q   ->  110 passed in 0.95s
```
