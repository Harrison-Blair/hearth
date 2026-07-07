---
id: FTHR-008
title: "Revoice scheduler + calendar-watcher announcements"
plumage: PLM-003
status: egg
priority: P1
depends_on: [FTHR-005]
authored: 2026-07-07T19:24:46Z
agent: fledge-orchestrate/planning
fledge_version: 0.2.0
---

# FTHR-008: Revoice scheduler + calendar-watcher announcements

## Description
Widens the tracer to the two proactive speech paths that bypass the pipeline:
the ReminderScheduler (due reminders spoken while idle, plus the catch-up
summary after downtime) and the CalendarWatcher (upcoming-event
announcements). Both currently synthesize plain text straight to TTS. After
this feather, each passes its announcement through the same injected
`Revoicer` before synthesis — the catch-up summary revoiced as **one call**
over the composed text (preamble + joined reminders), not per reminder — with
all FTHR-005 fallbacks (circuit, timeout, digit guard) applying unchanged.
Latency is invisible here: these fire while the assistant is idle.

Satisfies PLM-003 FC-4 (scheduler/watcher sites); completes AC-2.

## Affected Modules
- **`assistant/scheduling/scheduler.py`** — optional `Revoicer` injected;
  due-reminder text and the composed catch-up summary revoiced before
  `synthesize`.
- **`assistant/scheduling/calendar_watcher.py`** — same treatment for event
  announcements.
- **`assistant/app.py`** — pass the FTHR-005 `Revoicer` instance into both
  constructors (same object as the pipeline's — shared circuit state, so a
  down LLM discovered on a turn also short-circuits announcements).

## Approach
Test-first. Mirror FTHR-005's pipeline integration: constructor takes
`revoicer: Revoicer | None = None` (None → passthrough, keeping existing
tests valid); the announce path becomes
`text = await self._revoicer.revoice(text)` immediately before synthesis.
Failure handling stays inside `Revoicer` — the schedulers' own try/except
blocks around synthesis/playback are untouched. No config changes (FTHR-005's
fields govern behavior).

## Tests
- Extended `tests/test_scheduler.py`: a due reminder is revoiced before TTS
  (stub Revoicer records the call; spy TTS receives the styled text); the
  catch-up path makes exactly one revoice call over the composed summary;
  `revoicer=None` behaves byte-identical to today.
- Extended `tests/test_calendar_watcher.py`: announcement revoiced before
  TTS; dedupe/mark logic unaffected when revoice falls back to plain.

Implementation order is fixed: (1) write the tests; (2) confirm they FAIL
against unchanged code for the expected reason; (3) implement until they
pass.

## Acceptance Criteria
- [x] AC-1: The tests listed above were observed failing before
      implementation and pass after.
- [x] AC-2: Due-reminder, catch-up (one call), and calendar announcements
      all pass through the shared Revoicer before TTS (PLM-003 AC-2).
- [x] AC-3: With `revoicer=None` or persona disabled, both schedulers'
      spoken output is byte-identical to today; a failing revoice never
      drops or delays an announcement beyond `revoice_timeout_s`.
- [x] AC-4: `ruff check assistant tests` and the full suite pass without
      native extras or network.
