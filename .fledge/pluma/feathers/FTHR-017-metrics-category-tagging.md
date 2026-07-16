---
id: FTHR-017
title: Metrics category tagging
plumage: PLM-004
status: egg
priority: P2
depends_on: [FTHR-016, FTHR-013, FTHR-014]
authored: 2026-07-16T00:26:12Z
agent: fledge-orchestrate/planning
fledge_version: 0.5.5
---

# FTHR-017: Metrics category tagging

## Description
Tag PLM-003's per-call/per-turn metrics log lines and FTHR-014's
FAILED/timeout markers with `extra={"category": "metrics"}` so
FTHR-016's console formatter applies the `metrics` category's field
coloring to them, and register the `metrics` category's coloring rule in
FTHR-016's category registry. Depends on FTHR-016 (the formatter/registry
must exist), FTHR-013 (the per-call/per-turn log calls to tag), and
FTHR-014 (the FAILED/timeout marker log calls to tag).

## Affected Modules
- `hearth/loop.py` — the per-call and per-turn `logger.info(...)` calls
  `run_react_rounds`/`Loop.run_turn` add per FTHR-013, and the
  `logger.warning(...)` FAILED/timeout marker calls FTHR-014 adds. See
  `.fledge/nest/architecture.md` → "The two-tier brain" (`run_react_rounds`
  is the shared engine both call sites in this feather touch).
- `hearth/brain/openai_compat.py` — only if FTHR-013 ends up logging
  directly from `_OpenAICompatBackend.complete()` rather than solely from
  `run_react_rounds`; tag any such call site the same way. (FTHR-013's
  Approach places per-call logging in `run_react_rounds`, so this file may
  need no changes — confirm against FTHR-013's actual implementation before
  assuming no work here.)
- `hearth/logging_setup.py` — register the `metrics` category's
  field-coloring rule in the registry FTHR-016 establishes (e.g. distinct
  colors for the `in=`/`out=`/`thinking=`/`tok/s` segments of a metrics
  line, and a treatment for FAILED markers that's visually consistent with
  their `WARNING` level).

## Approach
1. Add `extra={"category": "metrics"}` to every `logger.info(...)` /
   `logger.warning(...)` call FTHR-013/FTHR-014 introduced for per-call
   metrics, per-turn summaries, and FAILED/timeout markers. Do not change
   any log message text, only add the `extra` kwarg.
2. In `hearth/logging_setup.py`, register a `"metrics"` entry in FTHR-016's
   category-coloring registry: a rule that, given the delimiter-joined
   `key=value` segments FTHR-013 produces, applies distinguishable coloring
   per segment (e.g. token counts one color, timing/tok-per-sec another) —
   exact color choices are an implementation detail, not a fresh interrogation
   point, as long as none of them reuse the ERROR/CRITICAL color FTHR-016
   reserved.
3. No changes to log message content, log levels beyond what FTHR-013/014
   already set, or to any test assertions those feathers already wrote for
   message content — this feather only adds the `category` tag and a
   registry entry, verified additively.

## Tests
Written test-first — run against the code as it stands after FTHR-016/013/014
(before this feather's changes) and confirm failure (no `category` present,
or the registry has no `"metrics"` entry so coloring falls back to
plain/universal), then implement until passing.
- `test_metrics_calls_carry_category_tag` (extends `test_loop.py`): assert,
  via `caplog`, that the `LogRecord`s produced by a turn's per-call and
  per-turn metrics lines each have `record.category == "metrics"`.
- `test_failed_marker_carries_category_tag` (extends `test_loop.py` /
  `test_brain_errors.py`): force a `BrainError` and assert the resulting
  FAILED marker's `LogRecord` also has `record.category == "metrics"`.
- `test_metrics_category_gets_registered_coloring` (extends
  `test_console_formatter.py`/`test_logging.py` from FTHR-016): format a
  real metrics-shaped log record with `category="metrics"` through the
  console formatter (color forced on) and assert it receives per-segment
  coloring distinct from the plain/universal fallback FTHR-016's
  uncategorized-record test already pins down — and assert none of its
  colors match the reserved ERROR/CRITICAL color.

## Acceptance Criteria
- [x] AC-1: The tests listed above were observed failing before implementation and pass after.
- [x] AC-2: Every per-call, per-turn, and FAILED/timeout-marker log call from FTHR-013/FTHR-014 carries `extra={"category": "metrics"}`, with no change to message text or log level. Satisfies PLM-004 FC-4.
- [x] AC-3: The console formatter's `metrics` category renders these lines with distinguishable per-segment coloring that never reuses the reserved ERROR/CRITICAL color, completing PLM-004 AC-3's metrics-category coverage (FTHR-016 covers the fallback/registry mechanism; this feather completes the `metrics` case).
