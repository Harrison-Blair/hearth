# FTHR-026 molt evidence — Concurrent veneer proof

Tests-only feather. One new file: `tests/test_gateway_concurrency.py`. No
production code added or changed. All commands run from the worktree root with
`python -m pytest` (worktree `hearth` on `sys.path[0]`, verified below).

Interpreter/import sanity:

```
$ python -c "import hearth; print(hearth.__file__)"
/tmp/.../scratchpad/FTHR-026/hearth/__init__.py     # worktree copy, not main
```

## AC-1

The three tests pass against unchanged production code.

```
$ python -m pytest tests/test_gateway_concurrency.py -v
tests/test_gateway_concurrency.py::test_two_veneers_connected_concurrently_are_both_served PASSED [ 33%]
tests/test_gateway_concurrency.py::test_concurrent_veneers_hold_isolated_conversations PASSED [ 66%]
tests/test_gateway_concurrency.py::test_engine_does_not_serialize_turns_across_veneers PASSED [100%]
============================== 3 passed in 0.04s ===============================
```

Because these tests describe behavior that already holds by construction, a
passing run alone proves nothing — see AC-2 for the break/restore that makes
each one real.

## AC-2

Each property was verified by breaking it, observing the test fail **for the
right reason**, then restoring. The break in each case is a temporary edit that
was reverted — production code and the shipped test both end unchanged (AC-1
re-run above is the restored state).

### FC-7 — serialize `run_turn` under a global lock

Break: wrapped `_GatedLoop.run_turn`'s body in `async with self._serialize:`
(a shared `asyncio.Lock`). Turn A acquires the lock and parks on the event; B
is queued behind A for the lock, so it never runs to set the event → deadlock.

```
$ python -m pytest tests/test_gateway_concurrency.py::test_engine_does_not_serialize_turns_across_veneers
>                   raise TimeoutError from exc_val
E                   TimeoutError
/usr/lib/python3.14/asyncio/timeouts.py:115: TimeoutError
FAILED ...::test_engine_does_not_serialize_turns_across_veneers
============================== 1 failed in 10.07s ==============================
```

Failed for the right reason: a clean, bounded `TimeoutError` (5s body wait +
5s bounded teardown), i.e. the serializing engine deadlocks. Restored → passes
(AC-1). Note: the shipped test's teardown (`_close`) bounds `wait_closed()` so a
stuck-in-engine turn surfaces as this legible timeout instead of a hung suite.

### FC-6 — force a shared `session_id` across connections

Break: `monkeypatch.setattr(hearth.gateway.server.uuid, "uuid4", lambda:
SimpleNamespace(hex="SHARED"))` at the top of the isolation test, so every
connection gets the same session id and B reconstructs A's history.

```
$ python -m pytest tests/test_gateway_concurrency.py::test_concurrent_veneers_hold_isolated_conversations
>           assert alpha not in json.dumps(req["messages"])
E           assert 'ALPHA-CANARY-9f3a1' not in '[{"role": "...ARY-2b7c4"}]'
E             'ALPHA-CANARY-9f3a1' is contained here:
E               ...content": "ALPHA-CANARY-9f3a1"}, {"role": "assistant", "content": "answer 1"}, {"role": "user", "content": "BRAVO-CANARY-2b7c4"}]
FAILED ...::test_concurrent_veneers_hold_isolated_conversations
============================== 1 failed in 0.03s ===============================
```

Failed for the right reason: A's canary text appears in the backend messages
for B's turn (asserted on message content, not session ids). Restored → passes.

### FC-5 — stall the second connection

Break: in `_BarrierLoop.run_turn`, made the second arriving turn hang
(`if self._arrived >= 2: await asyncio.Event().wait()`) so the second veneer is
never served and the barrier never fills.

```
$ python -m pytest tests/test_gateway_concurrency.py::test_two_veneers_connected_concurrently_are_both_served
>                   raise TimeoutError from exc_val
E                   TimeoutError
FAILED ...::test_two_veneers_connected_concurrently_are_both_served
============================== 1 failed in 10.07s ==============================
```

Failed for the right reason: with the second connection stalled, neither turn
completes and the bounded wait times out. Restored → passes.

## AC-3

`test_two_veneers_connected_concurrently_are_both_served` opens two loopback
connections inside a single `async with (... as ws_a, ... as ws_b)` — both are
open, neither closed before the other — then `asyncio.gather`s a turn on each.
`_BarrierLoop` answers no turn until both are simultaneously in flight, so a
pass is proof of concurrent service; sequential connect/turn/close could not
satisfy the barrier. Distinct per-connection session ids are confirmed by
`msgs_a[0]["text"] != msgs_b[0]["text"]`. Passes (AC-1); the FC-5 break (AC-2)
shows it fails if the second connection is not served.

## AC-4

`test_concurrent_veneers_hold_isolated_conversations` uses the **real `Loop`**
(history is reconstructed into the backend `messages` at `loop.py:283-293`)
behind a real `Gateway`, with a `MockTransport` backend recording every request
body. Both veneers stay connected; it asserts A's canary
(`ALPHA-CANARY-9f3a1`) appears **nowhere in the backend messages for B's turn**
(`assert alpha not in json.dumps(req["messages"])`) — not merely that session
ids differ. A guard also confirms A's canary *was* on the wire for A's own turn,
ruling out a false pass. Passes (AC-1); the FC-6 break (AC-2) shows it detects
leakage.

## AC-5

`test_engine_does_not_serialize_turns_across_veneers` gates turn A on turn B's
completion (`_GatedLoop`: A awaits `_b_done`; B sets it on the way out) and
bounds the whole thing with `asyncio.wait_for(..., timeout=TIMEOUT_S)`. Under a
non-serializing engine, B runs while A is parked and both finish; a serializing
engine deadlocks and times out (demonstrated under the FC-7 break, AC-2). Passes
(AC-1).

## AC-6

The proof uses a test-local fake veneer only: two simultaneous loopback
websocket clients (`websockets.connect` + `hearth.veneers.base.send_turn`) and
fake `Loop` doubles (`_BarrierLoop`, `_GatedLoop`) local to the test module. No
production code is added or changed — no second real surface, no production
concurrency machinery. `git status --short` shows only the new test file
(AC-7).

## AC-7

`tests/test_gateway_concurrency.py` is the only file added or changed.

```
$ git status --short
?? tests/test_gateway_concurrency.py
```

`tests/conftest.py`, `hearth/loop.py`, `hearth/gateway/**`, and
`hearth/veneers/**` are untouched, leaving FTHR-025 free to run concurrently.
(The `llm_config` fixture from the existing `conftest.py` is *used* by the
isolation test but `conftest.py` itself is not modified.)

## AC-8

No property failed against unchanged code. All three passed on first run
(AC-1); the only failures observed were the deliberate, reverted breaks in
AC-2. Nothing was raised as a finding and no production code was touched.

## AC-9

`ruff check .` is clean and the full existing suite passes.

```
$ ruff check .
All checks passed!

$ python -m pytest -q
122 passed in 1.09s
```
