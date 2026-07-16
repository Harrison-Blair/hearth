# FTHR-016 molt evidence — Console color formatter

All commands run from the worktree root:
`/tmp/claude-1000/-home-penguin-source-hearth/f87e11cc-2fbb-4815-ae23-96a05fcf4a7b/scratchpad/FTHR-016`
with `PYTHONPATH="$(pwd)"` set so the worktree's copy of `hearth/` shadows the
editable install (which otherwise resolves to the checked-out main repo path)
— required in this worktree, `.venv` is a symlink to the shared repo venv.

## AC-1

The tests listed in the feather spec's Tests section were observed failing
before implementation, then passing after.

**Pre-implementation (unchanged code) — `PYTHONPATH="$(pwd)" .venv/bin/pytest tests/test_console_formatter.py -v`:**

```
============================= test session starts ==============================
platform linux -- Python 3.14.6, pytest-9.1.1, pluggy-1.6.0 -- /home/penguin/source/hearth/.venv/bin/python3
cachedir: .pytest_cache
rootdir: /tmp/claude-1000/-home-penguin-source-hearth/f87e11cc-2fbb-4815-ae23-96a05fcf4a7b/scratchpad/FTHR-016
configfile: pyproject.toml
plugins: asyncio-1.4.0, anyio-4.14.1
asyncio: mode=Mode.AUTO, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collecting ... collected 6 items

tests/test_console_formatter.py::test_delimiter_present_in_every_line FAILED [ 16%]
tests/test_console_formatter.py::test_error_color_is_exclusive FAILED    [ 33%]
tests/test_console_formatter.py::test_unknown_category_falls_back_to_level_only FAILED [ 50%]
tests/test_console_formatter.py::test_no_color_when_not_a_tty FAILED     [ 66%]
tests/test_console_formatter.py::test_no_color_when_no_color_env_set FAILED [ 83%]
tests/test_console_formatter.py::test_file_handler_unaffected FAILED     [100%]

=================================== FAILURES ===================================
_____________________ test_delimiter_present_in_every_line _____________________

    def test_delimiter_present_in_every_line():
>       from hearth.logging_setup import ColorFormatter
E       ImportError: cannot import name 'ColorFormatter' from 'hearth.logging_setup'

tests/test_console_formatter.py:35: ImportError
________________________ test_error_color_is_exclusive _________________________
    def test_error_color_is_exclusive(monkeypatch):
>       from hearth.logging_setup import _CATEGORY_COLORS, ColorFormatter
E       ImportError: cannot import name '_CATEGORY_COLORS' from 'hearth.logging_setup'

tests/test_console_formatter.py:46: ImportError
[... the remaining 4 tests fail with the same ImportError: ColorFormatter
does not exist yet on unchanged code — all six fail for the expected reason,
not a setup/collection error unrelated to the feature ...]

=========================== short test summary info ============================
FAILED tests/test_console_formatter.py::test_delimiter_present_in_every_line
FAILED tests/test_console_formatter.py::test_error_color_is_exclusive - Impor...
FAILED tests/test_console_formatter.py::test_unknown_category_falls_back_to_level_only
FAILED tests/test_console_formatter.py::test_no_color_when_not_a_tty - Import...
FAILED tests/test_console_formatter.py::test_no_color_when_no_color_env_set
FAILED tests/test_console_formatter.py::test_file_handler_unaffected - Import...
============================== 6 failed in 0.02s ===============================
```

(One test, `test_error_color_is_exclusive`, was also fixed mid-implementation:
its first version counted the shared ANSI reset code `\x1b[0m` as a "color",
which spuriously "leaked" into every colored output including DEBUG. Excluded
the reset code from the comparison set — a test-correctness fix, not a
weakening; the assertion still requires the ERROR/CRITICAL color to appear
nowhere else.)

**Post-implementation — `PYTHONPATH="$(pwd)" .venv/bin/pytest tests/test_console_formatter.py -v`:**

```
============================= test session starts ==============================
platform linux -- Python 3.14.6, pytest-9.1.1, pluggy-1.6.0 -- /home/penguin/source/hearth/.venv/bin/python3
cachedir: .pytest_cache
rootdir: /tmp/claude-1000/-home-penguin-source-hearth/f87e11cc-2fbb-4815-ae23-96a05fcf4a7b/scratchpad/FTHR-016
configfile: pyproject.toml
plugins: asyncio-1.4.0, anyio-4.14.1
asyncio: mode=Mode.AUTO, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collecting ... collected 6 items

tests/test_console_formatter.py::test_delimiter_present_in_every_line PASSED [ 16%]
tests/test_console_formatter.py::test_error_color_is_exclusive PASSED    [ 33%]
tests/test_console_formatter.py::test_unknown_category_falls_back_to_level_only PASSED [ 50%]
tests/test_console_formatter.py::test_no_color_when_not_a_tty PASSED     [ 66%]
tests/test_console_formatter.py::test_no_color_when_no_color_env_set PASSED [ 83%]
tests/test_console_formatter.py::test_file_handler_unaffected PASSED     [100%]

============================== 6 passed in 0.01s ===============================
```

**Full repo suite (no regressions) — `PYTHONPATH="$(pwd)" .venv/bin/pytest`:**

```
tests/test_brain_guard.py ..                                             [ 12%]
tests/test_config.py ..........                                          [ 24%]
tests/test_console_formatter.py ......                                   [ 31%]
tests/test_consult_brain.py ....                                         [ 36%]
tests/test_e2e_veneer.py ....                                            [ 40%]
tests/test_event_log.py .                                                [ 42%]
tests/test_layer2_reader.py ...                                          [ 45%]
tests/test_local_backend.py .....                                        [ 51%]
tests/test_logging.py .........                                          [ 62%]
tests/test_loop.py ...                                                   [ 66%]
tests/test_loop_tools.py ......                                          [ 73%]
tests/test_orchestrator_persona.py ..                                    [ 75%]
tests/test_remote_backend.py .                                           [ 77%]
tests/test_router.py ....                                                [ 81%]
tests/test_veneer.py ....                                                [ 86%]
tests/test_veneer_client.py ..                                           [ 89%]
tests/test_veneer_errors.py .....                                        [ 95%]
tests/test_wikipedia.py ....                                             [100%]

============================== 83 passed in 0.84s ==============================
```

`ruff check hearth/logging_setup.py tests/test_console_formatter.py` → `All checks passed!`

## AC-2

`test_delimiter_present_in_every_line` formats both a plain record (no
category) and a `category="metrics"`-tagged record through `ColorFormatter`
and asserts ` │ ` appears in both outputs. `ColorFormatter.format()`
(`hearth/logging_setup.py`) always joins `[ts_level, message]` with
`_DELIMITER = " │ "` regardless of category or color state — verified
passing above (see AC-1 post-implementation output,
`test_delimiter_present_in_every_line PASSED`). `test_no_color_when_not_a_tty`
and `test_no_color_when_no_color_env_set` further assert the delimiter
survives when color is suppressed.

## AC-3

`test_error_color_is_exclusive` formats one synthetic record per level
(DEBUG/INFO/WARNING/ERROR/CRITICAL) plus one per registered category
(a synthetic `"demo"` category injected via `monkeypatch.setitem` — no real
category is registered yet, matching the spec's "no other feather's call
sites need to exist yet"), with color forced on (`sys.stdout.isatty` mocked
`True`, `NO_COLOR` cleared). It collects every non-reset ANSI code per
output and asserts the ERROR/CRITICAL code set is disjoint from every other
output's code set, and present in both ERROR and CRITICAL. Implementation:
`_LEVEL_COLORS` in `hearth/logging_setup.py` maps only `ERROR`/`CRITICAL` to
`"\x1b[1;31m"` (bold red) — no other level and no category rule in
`_CATEGORY_COLORS` uses that code. Passing: see AC-1 post-implementation
output, `test_error_color_is_exclusive PASSED`.

## AC-4

`test_unknown_category_falls_back_to_level_only` formats a record with
`category="not-a-real-category"` and a record with no `category` attribute
at all (pinning `created`/`msecs` so only category handling differs) and
asserts identical output. `ColorFormatter.format()` reads
`getattr(record, "category", "plain")` and only applies a category rule when
`category in _CATEGORY_COLORS`; both an unregistered string and the "plain"
default miss the (currently empty) registry and fall through to the
universal timestamp+level coloring only — the same path a real third-party
`websockets` record (which never carries `.category`) takes. Passing: see
AC-1 post-implementation output,
`test_unknown_category_falls_back_to_level_only PASSED`. The registry
dispatch mechanism itself (a registered category *does* get its rule
applied) is additionally proven by `test_error_color_is_exclusive`'s
`"demo"` category output differing from the plain/level-only outputs.

## AC-5

`test_no_color_when_not_a_tty` mocks `sys.stdout.isatty` to `False` and
asserts the formatted output contains no `\x1b[` sequence while still
containing ` │ ` and the message content. `test_no_color_when_no_color_env_set`
mocks `isatty` `True` but sets `NO_COLOR=1` and asserts the same. Both pass
against `ColorFormatter.format()`'s `use_color = sys.stdout.isatty() and not
os.environ.get("NO_COLOR")` guard, which gates both `_LEVEL_COLORS` and
`_CATEGORY_COLORS` lookups. Passing: see AC-1 post-implementation output,
both tests `PASSED`.

## AC-6

`test_file_handler_unaffected` calls `setup_logging(LoggingConfig(...,
console=True))`, locates the `RotatingFileHandler` on the root logger, and
asserts its formatter is not a `ColorFormatter` instance. It then logs a
record and reads the file directly, asserting the delimiter (` │ `) and ANSI
codes (`\x1b[`) are both absent while the message content is present. The
file handler's formatter (`hearth/logging_setup.py::setup_logging`) is
untouched — the `formatter = logging.Formatter(...)` construction and its
assignment to `handler` are unchanged from before this feather; only the
console `StreamHandler`'s `setFormatter` call was changed, from `formatter`
to `ColorFormatter()`. Passing: see AC-1 post-implementation output,
`test_file_handler_unaffected PASSED`.
