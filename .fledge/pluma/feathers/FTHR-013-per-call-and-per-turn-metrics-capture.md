---
id: FTHR-013
title: Per-call and per-turn metrics capture
plumage: PLM-003
status: pipping
priority: P1
depends_on: []
authored: 2026-07-15T23:47:50Z
agent: fledge-orchestrate/planning
fledge_version: 0.5.5
---

# FTHR-013: Per-call and per-turn metrics capture

## Description
Deliver the tracer-bullet slice of PLM-003 end-to-end for the happy path:
capture token counts, thinking/reasoning tokens (when reported), and
wall-clock duration for every LLM completion call — on both the local
Ollama-style backend and the remote OpenRouter-style backend, via the single
shared implementation both build on — and log an INFO-level line after every
successful call plus one aggregate summary line at the end of every
user-facing turn, including whatever happened inside a nested
`consult_brain` invocation. Failure/timeout marker logging is a separate
feather (FTHR-014, depends on this one).

## Affected Modules
- `hearth/brain/base.py` — `BrainResult` (see `.fledge/nest/data-model.md` →
  "Brain boundary types"). Widen with new optional fields; this dataclass is
  documented as frozen ("FTHR-004/FTHR-006 build on them without changing
  shape") — update that docstring note to acknowledge the widening rather
  than silently contradicting it.
- `hearth/brain/openai_compat.py` — `_OpenAICompatBackend.complete()` (see
  `.fledge/nest/architecture.md` → "Key seams" / `hearth/brain/`). The one
  shared request/parse implementation `LocalBackend` and `RemoteBackend`
  both build on (`hearth/brain/local.py`, `hearth/brain/remote.py` are thin
  config-bound subclasses with no logic of their own) — capturing here
  covers both backend types with one change.
- `hearth/loop.py` — `run_react_rounds` (shared ReAct engine, used by both
  the top-level orchestrator turn and the nested consult) and
  `Loop.run_turn` (see `.fledge/nest/architecture.md` → "The two-tier
  brain" / `run_react_rounds` note: "do not duplicate this loop logic
  elsewhere").
- `hearth/tools/consult.py` — `BrainConsult.__call__` (nested ReAct on the
  `tool` tier); must surface its aggregate metrics back to the caller so
  `Loop.run_turn`'s per-turn line reflects nested-tier work too.

## Approach
1. **Widen `BrainResult`** (`hearth/brain/base.py`) with new fields, all
   optional/defaulted so no existing construction site breaks:
   `model: str = ""`, `prompt_tokens: int | None = None`,
   `completion_tokens: int | None = None`,
   `reasoning_tokens: int | None = None`, `total_tokens: int | None = None`,
   `duration_s: float | None = None`. Update the module docstring's "frozen"
   note to say the boundary shape is frozen for router/tool call sites but
   may gain additive, defaulted observability fields.
2. **Capture in `_OpenAICompatBackend.complete()`** (`hearth/brain/openai_compat.py`):
   - Bracket the `await self._client.post("/chat/completions", ...)` call
     with `time.monotonic()` before and after; set `duration_s` on the
     returned `BrainResult` regardless of whether `usage` is present.
   - Parse `body.get("usage") or {}`: `prompt_tokens`, `completion_tokens`,
     `total_tokens` map directly (default `None` when the key is absent —
     never fabricate a `0`). Read
     `usage.get("completion_tokens_details", {}).get("reasoning_tokens")`
     for `reasoning_tokens` (`None` when absent — most non-reasoning models
     won't include this).
   - Set `model=self._config.model` on the result (already available on
     `self._config`, no new plumbing needed).
   - This is the only capture site; `LocalBackend`/`RemoteBackend` inherit
     it unchanged.
3. **Per-call logging in `run_react_rounds`** (`hearth/loop.py`): after each
   `result = await brain.complete(...)` (both the initial call before the
   loop and each subsequent round inside the `while` loop), emit one INFO
   log line via the module's existing `logger`. Use a 1-based round counter
   for the log line (the initial call is round 1; each iteration of the
   existing `while result.tool_calls and round_count < round_cap:` loop is
   round 2, 3, …). Line contents: `tier`, `model`, `round=N`, `in=`
   (prompt_tokens), `out=` (completion_tokens), `thinking=` (the reasoning
   token count, or the literal string `n/a` when `reasoning_tokens is
   None`), `duration_s` formatted to one decimal with an `s` suffix, and
   `tok/s` computed as `completion_tokens / duration_s` (guard
   `duration_s <= 0` or `completion_tokens is None` to avoid a
   `ZeroDivisionError` — print `n/a` for tok/s in that case). Accumulate
   each round's `(prompt_tokens, completion_tokens, duration_s)` into local
   running totals inside `run_react_rounds` and return them via a small
   dataclass alongside `BrainResult` (or attached to the returned
   `BrainResult` — pick whichever keeps `run_react_rounds`'s existing return
   type contract intact for its two callers; a nested internal type is fine
   since both call sites are being touched in this same feather anyway).
4. **Per-turn aggregation in `Loop.run_turn`** (`hearth/loop.py`): sum the
   metrics from the orchestrator's own `run_react_rounds` call with whatever
   `consult_dispatch`/`BrainConsult` reports from its nested rounds (see
   step 5), then log one INFO summary line: turn number (see below), round
   count (orchestrator rounds + nested consult rounds), call count, total
   `in=`/`out=` tokens, total wall time, and blended `tok/s` (total
   completion tokens / total duration across every call in the turn).
   Compute the session-sequential turn number by counting prior
   `final_answer` events for `session_id` via `self._log.read_session(session_id)`
   (already called earlier in `run_turn` for history reconstruction — reuse
   that result rather than re-querying) and adding 1.
5. **Thread nested consult metrics back** (`hearth/tools/consult.py`):
   `BrainConsult.__call__` already calls `run_react_rounds` directly: capture
   its per-round metrics the same way (steps 3–4 apply symmetrically here,
   since `consult.py` also calls `run_react_rounds`) and expose the
   aggregate on the object (e.g. an attribute set after the call, or a
   richer return value) that `Loop.run_turn`'s `consult_dispatch` closure
   can read after `await self._consult(...)` returns, so the per-turn
   summary line's totals include the nested tier's calls. Keep
   `BrainConsult.__call__`'s existing return type (a plain `str` findings
   string) unchanged for backward compatibility with its role as a tool
   `dispatch` callable — surface the metrics via a side attribute/companion
   object rather than changing what it returns to the ReAct loop's tool
   dispatch protocol.
6. No config, no wire-protocol changes: metrics never touch
   `hearth/veneer/protocol.py::serialize`'s whitelist.

## Tests
Written test-first — run each new/modified test against the unchanged code
first and confirm it fails for the expected reason (missing fields / no log
output), then implement until it passes.
- `test_local_backend.py` / `test_remote_backend.py`: extend the canned
  chat-completion fixture to include a `usage` block; assert
  `BrainResult.prompt_tokens`/`completion_tokens`/`total_tokens`/`model` are
  populated correctly for both `LocalBackend` and `RemoteBackend`. Add a
  case with `usage.completion_tokens_details.reasoning_tokens` present
  (asserts `reasoning_tokens` is set) and a case where `usage` is entirely
  absent from the response body (asserts every numeric field is `None`,
  never `0`, and `complete()` doesn't raise).
- `test_local_backend.py`: assert `duration_s` is a positive float after a
  call (mock transport can add a tiny synthetic delay, or just assert
  `duration_s is not None and duration_s >= 0`).
- `test_loop.py`: assert (via `caplog`) that a single-round turn logs one
  per-call line containing `tier=`, `round=1`, `in=`, `out=`, and
  `thinking=n/a` (canned response has no reasoning tokens), and one
  per-turn summary line containing the turn's sequential number and
  aggregate totals. Add a second turn in the same session and assert the
  turn number increments.
- `test_loop_tools.py` / `test_consult_brain.py`: exercise a turn where
  `consult_brain` fires (a nested ReAct round on the `tool`
  tier); assert the per-turn summary's total tokens/call count include both
  the orchestrator's own call(s) and the nested consult's call(s) — not
  just the orchestrator's.
- Regression check: run the existing `test_veneer.py` wire-whitelist tests
  (`forbidden_keys` assertions) unmodified and confirm they still pass,
  proving no metrics field leaks onto the wire (PLM-003 AC-6).

## Acceptance Criteria
- [x] AC-1: The tests listed above were observed failing before implementation and pass after.
- [x] AC-2: `BrainResult` carries `model`, `prompt_tokens`, `completion_tokens`, `reasoning_tokens`, `total_tokens`, and `duration_s`, populated identically by both `LocalBackend` and `RemoteBackend` via the shared `_OpenAICompatBackend.complete()`, with unavailable fields left `None` rather than `0`. Satisfies PLM-003 FC-1, FC-2, FC-6.
- [x] AC-3: A per-call INFO log line is emitted after every successful `brain.complete()` inside `run_react_rounds`, showing tier, model, round number, input/output tokens, a `thinking=` value (numeric or literal `n/a`), duration, and tokens/sec. Satisfies PLM-003 FC-1, FC-2; PLM-003 AC-1, AC-5.
- [x] AC-4: A per-turn INFO summary log line is emitted once per `Loop.run_turn` call, showing the session-sequential turn number, total round count, call count, total input/output tokens, total wall-clock time, and blended tokens/sec, and its totals correctly include metrics from a nested `consult_brain` call when one occurs during the turn. Satisfies PLM-003 FC-3, FC-4; PLM-003 AC-2, AC-3.
- [x] AC-5: Metrics logging is INFO-level on the existing logging setup with no new config field, and the existing wire-protocol whitelist tests (`test_veneer.py`) pass unmodified. Satisfies PLM-003 FC-7; PLM-003 AC-6.
