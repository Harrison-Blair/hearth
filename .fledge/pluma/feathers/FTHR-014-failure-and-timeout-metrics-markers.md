---
id: FTHR-014
title: Failure and timeout metrics markers
plumage: PLM-003
status: fledged
priority: P1
depends_on: [FTHR-013]
authored: 2026-07-15T23:49:19Z
agent: fledge-orchestrate/planning
fledge_version: 0.5.5
---

# FTHR-014: Failure and timeout metrics markers

## Description
Widen FTHR-013's happy-path metrics logging with the failure case: when an
LLM call raises `BrainError` or a turn/consult times out, log a distinct
one-line FAILED-style marker instead of a normal per-call metrics line (and
instead of silence), and reflect the failure in the per-turn summary's call
count without polluting its token/tokens-per-second math. Depends on
FTHR-013 because it reuses the per-call/per-turn logging and aggregation
plumbing that feather builds.

## Affected Modules
- `hearth/loop.py` — `run_react_rounds` (wrap each `await brain.complete(...)`
  call added in FTHR-013 with failure handling) and `Loop.run_turn` (its
  existing `except asyncio.TimeoutError` handler around
  `asyncio.wait_for(run_react_rounds(...), timeout=...)`). See
  `.fledge/nest/architecture.md` → "The two-tier brain" /
  `.fledge/nest/conventions.md` → "Error handling" (retry policy,
  `BrainError.reason`/`.detail` split).
- `hearth/tools/consult.py` — `BrainConsult.__call__`'s existing
  `except BrainError` / `except asyncio.TimeoutError` handlers (it already
  catches both and degrades to a plain-text observation — see
  `.fledge/nest/conventions.md` → "`BrainConsult` degrades `BrainError`/
  timeout to a plain-text observation rather than raising").
- No further changes to `hearth/brain/base.py` or
  `hearth/brain/openai_compat.py` — this feather only adds logging/counting
  around call sites FTHR-013 already touches.

## Approach
1. **Per-call `BrainError` marker** (`hearth/loop.py`, inside
   `run_react_rounds`): wrap the `await brain.complete(...)` calls (both the
   initial call and the in-loop calls FTHR-013 already instruments) so that
   when `brain.complete()` raises `BrainError`, a one-line `logger.warning(...)`
   marker is emitted before re-raising — unchanged propagation behavior,
   just observed on the way out. Marker contents: `tier`, `round=N` (same
   1-based counter FTHR-013 established), `FAILED`, `reason="<BrainError.reason>"`
   (client-safe field only — never log `.detail`, which may carry raw HTTP
   body text; see `conventions.md`'s error-handling note), and
   `after=<elapsed>s` measured the same way FTHR-013 measures `duration_s`
   (wall-clock from just before the request to the exception).
2. **Turn/consult-level timeout marker**: the existing
   `except asyncio.TimeoutError:` blocks in `Loop.run_turn` (around
   `asyncio.wait_for(run_react_rounds(...), timeout=self._config.agent.turn_timeout_s)`)
   and `BrainConsult.__call__` (around its own `asyncio.wait_for(...,
   timeout=self._config.agent.consult_timeout_s)`) each log one `logger.warning(...)`
   marker line noting the timeout (tier/label + elapsed time up to cancellation), in
   addition to their existing fallback behavior (`Loop.run_turn`'s
   "that took too long" answer text; `BrainConsult`'s degraded findings
   string) — neither existing behavior changes, this only adds a log line.
3. **Failure counting in the per-turn summary**: extend the aggregation
   FTHR-013 built in `Loop.run_turn` so a failed/timed-out call increments
   the turn's call count and adds its elapsed time to the turn's total wall
   time, but contributes zero tokens and is excluded from the blended
   tokens/sec denominator's numerator (it produced no completion tokens).
   When at least one call in the turn failed, the per-turn summary line
   shows the failure count alongside the call count, e.g.
   `calls=2 (1 failed)`; when none failed, the line is unchanged from
   FTHR-013's format (no `(0 failed)` clutter).
4. Reuse `BrainError.reason`/`.detail` exactly as already defined in
   `hearth/brain/errors.py` — no new exception types or fields.

## Tests
Written test-first — run each against the unchanged (FTHR-013-only) code
first and confirm it fails for the expected reason, then implement until it
passes.
- `test_brain_errors.py` or `test_loop.py`: force a `BrainError` from a mock
  transport handler (as existing tests already do for retry/timeout cases)
  and assert (via `caplog`) a FAILED marker line is logged containing
  `tier=`, `round=`, `FAILED`, and the `BrainError.reason` string — and
  assert `.detail` content never appears in the log output.
- `test_loop.py`: assert that after a forced `BrainError`, the surrounding
  turn's per-turn summary (if the turn completes, e.g. via `consult_brain`
  degrading rather than propagating) shows the failure in its call count
  (`(1 failed)`) and that the turn's total/blended tokens exclude the
  failed call's contribution.
- `test_loop_tools.py` (extending its existing timeout-simulation pattern,
  e.g. `asyncio.sleep()` in a mock handler / short `timeout=0.05s` configs):
  force a turn-level timeout and assert a timeout marker is logged from
  `Loop.run_turn`'s existing `except asyncio.TimeoutError` handler, without
  changing the existing "that took too long" answer-text assertion already
  covered by prior tests.
- `test_consult_brain.py` (same timeout-simulation pattern): force a
  consult-level timeout and assert a timeout marker is logged from
  `BrainConsult.__call__`'s existing `except asyncio.TimeoutError` handler,
  without changing its existing degraded-findings-string assertion.
- Regression check: re-run FTHR-013's per-call/per-turn happy-path tests
  unmodified and confirm they still pass (no failure-marker logic fires on
  the success path).

## Acceptance Criteria
- [x] AC-1: The tests listed above were observed failing before implementation and pass after.
- [x] AC-2: A `BrainError` raised from `brain.complete()` inside `run_react_rounds` produces a one-line FAILED marker logged at `WARNING` level (tier, round, `BrainError.reason`, elapsed time) before propagating unchanged, and never logs `BrainError.detail`. Satisfies PLM-003 FC-5; PLM-003 AC-4.
- [x] AC-3: A turn-level timeout (`Loop.run_turn`) and a consult-level timeout (`BrainConsult.__call__`) each log a `WARNING`-level timeout marker from their existing `except asyncio.TimeoutError` handlers, without changing either handler's existing fallback behavior (answer text / degraded findings string). Satisfies PLM-003 FC-5; PLM-003 AC-4.
- [x] AC-4: The per-turn summary line counts a failed/timed-out call toward the turn's call count and total wall time, shows a `(K failed)` suffix when `K > 0`, and excludes the failed call from the turn's token/tokens-per-second totals. Satisfies PLM-003 FC-5; PLM-003 AC-4.
- [x] AC-5: FTHR-013's happy-path per-call and per-turn tests still pass unmodified (no failure-marker logic triggers on successful calls).
