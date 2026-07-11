# FTHR-005 molt evidence — Layer-2 read seam and no-op consumer

## AC-1: Tests observed failing before implementation, passing after

Tests: `tests/test_layer2_reader.py::test_read_since_cursor_ordered`,
`::test_noop_consumer_pulls_events`, `::test_write_path_unaffected_without_consumer`.

### Pre-implementation run (FAILING)

Command: `.venv/bin/python -m pytest tests/test_layer2_reader.py -v`

Ran against the repo state before `hearth/memory/reader.py` and
`hearth/memory/consumer.py` existed. Fails at collection with the expected
`ModuleNotFoundError` for the not-yet-created seam modules (not a setup error
or unrelated test):

```
============================= test session starts ==============================
platform linux -- Python 3.14.6, pytest-9.1.1, pluggy-1.6.0 -- /home/penguin/source/hearth/.fledge/burrows/FTHR-005/.venv/bin/python
cachedir: .pytest_cache
rootdir: /home/penguin/source/hearth/.fledge/burrows/FTHR-005
configfile: pyproject.toml
plugins: asyncio-1.4.0, anyio-4.14.1
asyncio: mode=Mode.AUTO, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collecting ... collected 0 items / 1 error

==================================== ERRORS ====================================
_________________ ERROR collecting tests/test_layer2_reader.py _________________
ImportError while importing test module '/home/penguin/source/hearth/.fledge/burrows/FTHR-005/tests/test_layer2_reader.py'.
Hint: make sure your test modules/packages have valid Python names.
Traceback:
/usr/lib/python3.14/importlib/__init__.py:88: in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
tests/test_layer2_reader.py:5: in <module>
    from hearth.memory.consumer import NoOpConsumer, pull_once
E   ModuleNotFoundError: No module named 'hearth.memory.consumer'
=========================== short test summary info ============================
ERROR tests/test_layer2_reader.py
!!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
=============================== 1 error in 0.05s ===============================
```

### Post-implementation run (PASSING)

Command: `.venv/bin/python -m pytest tests/test_layer2_reader.py -v`

```
============================= test session starts ==============================
platform linux -- Python 3.14.6, pytest-9.1.1, pluggy-1.6.0 -- /home/penguin/source/hearth/.fledge/burrows/FTHR-005/.venv/bin/python
cachedir: .pytest_cache
rootdir: /home/penguin/source/hearth/.fledge/burrows/FTHR-005
configfile: pyproject.toml
plugins: asyncio-1.4.0, anyio-4.14.1
asyncio: mode=Mode.AUTO, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collecting ... collected 3 items

tests/test_layer2_reader.py::test_read_since_cursor_ordered PASSED       [ 33%]
tests/test_layer2_reader.py::test_noop_consumer_pulls_events PASSED      [ 66%]
tests/test_layer2_reader.py::test_write_path_unaffected_without_consumer PASSED [100%]

============================== 3 passed in 0.01s ===============================
```

Full suite also passes after implementation (`.venv/bin/python -m pytest`): 13 passed
(existing FTHR-002 tests unaffected).

## AC-2: Read-side, cursor-based, ordered pull interface exists and is typed

`hearth/memory/reader.py` — `EventReader(log: EventLog)`:
- `read_since(cursor: int, limit: int) -> list[Event]` — SQL `WHERE id > ? ORDER BY id LIMIT ?`,
  returns `Event` dataclass instances (reused from `hearth/memory/log.py`), ascending by `id`.
- `latest_cursor() -> int` — `SELECT MAX(id)`, returns `0` when empty (`row[0] or 0`).
- Fully typed signatures; read-only — issues only `SELECT` statements, no writes.

Verified by `test_read_since_cursor_ordered`:
- Appends 5 events, confirms `latest_cursor()` equals the last id.
- `read_since(ids[1], limit=100)` returns exactly the events after the 2nd, in ascending id order.
- `read_since(0, limit=2)` respects the `limit` cap.
- A fresh empty log's `latest_cursor()` returns `0`.

```
tests/test_layer2_reader.py::test_read_since_cursor_ordered PASSED
```

## AC-3: No-op consumer stub implements the Layer-2 consumer protocol

`hearth/memory/consumer.py`:
- `Layer2Consumer(Protocol)` — `async def consume(self, events: list[Event]) -> None`.
- `NoOpConsumer` — implements `consume`, does nothing.
- `pull_once(reader, consumer, cursor) -> int` — `read_since` → `consumer.consume` → advance
  cursor to the last pulled event's id (no scheduler; a single poll step). Not wired into any
  daemon/loop — the seam is available and tested, not started.

Verified by `test_noop_consumer_pulls_events`:
- A `SpyConsumer` receives appended events in order via `pull_once`.
- Returned cursor equals `reader.latest_cursor()` after the pull.
- `NoOpConsumer` runs through the same `pull_once` path with no observable effect, cursor still
  advances correctly.

```
tests/test_layer2_reader.py::test_noop_consumer_pulls_events PASSED
```

## AC-4: Write path uncoupled from and unaffected by any consumer

- `hearth/memory/log.py` is untouched by this feather — confirmed empty diff:
  `git diff main -- hearth/memory/log.py` produces no output.
- `EventLog` has no reference to `EventReader` or any consumer type; `reader.py`/`consumer.py`
  import `hearth.memory.log`, never the reverse.

Verified by `test_write_path_unaffected_without_consumer`:
- Appends two events with no `EventReader` or consumer ever constructed; `read_session` returns
  both, proving the write path (and its own read path from FTHR-002) works standalone.
- Asserts `EventLog` exposes no `consumer`, `reader`, or `attach_consumer` attribute — no coupling
  surface exists.

```
tests/test_layer2_reader.py::test_write_path_unaffected_without_consumer PASSED
```

Command used for the `git diff` claim above:

```
$ git diff main -- hearth/memory/log.py
$ echo $?
0
```

(no output — file unchanged since branching from main)
