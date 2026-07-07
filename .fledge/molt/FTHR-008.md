# FTHR-008 molt evidence: Revoice scheduler + calendar-watcher announcements

## AC-1

Tests listed in the spec's Tests section were observed failing before
implementation (unchanged code) and passing after implementation.

### Pre-implementation (failing)

Command:

```
source .venv/bin/activate && pytest tests/test_scheduler.py tests/test_calendar_watcher.py -v
```

Verbatim output (relevant excerpt — full run: 4 failed, 26 passed):

```
collecting ... collected 30 items

tests/test_scheduler.py::test_fires_due_deletes_and_skips_future PASSED  [  3%]
tests/test_scheduler.py::test_transient_failure_retries_then_speaks PASSED [  6%]
tests/test_scheduler.py::test_permanent_failure_defers_instead_of_deleting PASSED [ 10%]
tests/test_scheduler.py::test_recurring_reminder_survives_exhausted_retries PASSED [ 13%]
tests/test_scheduler.py::test_recurring_reminder_rearms_instead_of_deleting PASSED [ 16%]
tests/test_scheduler.py::test_catch_up_rearms_recurring_deletes_oneshot PASSED [ 20%]
tests/test_scheduler.py::test_boot_catch_up_coalesces_into_one_summary PASSED [ 23%]
tests/test_scheduler.py::test_steady_state_fires_individually_not_summarized PASSED [ 26%]
tests/test_scheduler.py::test_announcement_waits_for_arbiter PASSED      [ 30%]
tests/test_scheduler.py::test_standdown_delays_reminders_until_resume PASSED [ 33%]
tests/test_scheduler.py::test_standdown_preserves_boot_catchup PASSED    [ 36%]
tests/test_scheduler.py::test_due_reminder_is_revoiced_before_tts FAILED [ 40%]
tests/test_scheduler.py::test_catch_up_summary_revoiced_exactly_once FAILED [ 43%]
tests/test_scheduler.py::test_no_revoicer_is_byte_identical_to_today PASSED [ 46%]
tests/test_calendar_watcher.py::test_announces_event_in_lead_window_with_minutes PASSED [ 50%]
tests/test_calendar_watcher.py::test_never_reannounces_on_later_polls PASSED [ 53%]
tests/test_calendar_watcher.py::test_dedupe_survives_restart PASSED      [ 56%]
tests/test_calendar_watcher.py::test_moved_event_is_reannounced_with_new_time PASSED [ 60%]
tests/test_calendar_watcher.py::test_all_day_events_are_skipped PASSED   [ 63%]
tests/test_calendar_watcher.py::test_disabled_watcher_never_fetches PASSED [ 66%]
tests/test_calendar_watcher.py::test_voice_toggle_enables_the_running_loop PASSED [ 70%]
tests/test_calendar_watcher.py::test_provider_failure_survives_and_announces_next_poll PASSED [ 73%]
tests/test_calendar_watcher.py::test_speech_failure_is_retried_next_poll PASSED [ 76%]
tests/test_calendar_watcher.py::test_announcement_waits_for_arbiter PASSED [ 80%]
tests/test_calendar_watcher.py::test_imminent_event_says_now PASSED      [ 83%]
tests/test_calendar_watcher.py::test_standdown_skips_announcements PASSED [ 86%]
tests/test_calendar_watcher.py::test_announcement_is_revoiced_before_tts FAILED [ 90%]
tests/test_calendar_watcher.py::test_no_revoicer_is_byte_identical_to_today PASSED [ 93%]
tests/test_calendar_watcher.py::test_dedupe_unaffected_when_revoice_falls_back_to_plain FAILED [ 96%]
tests/test_calendar_watcher.py::test_blocked_event_is_not_announced_or_marked PASSED [100%]

=================================== FAILURES ===================================
___________________ test_due_reminder_is_revoiced_before_tts ___________________

    async def test_due_reminder_is_revoiced_before_tts():
        store = ReminderStore(":memory:")
        store.add(50.0, "past", created_at=0.0)
        tts, out = FakeTTS(), FakeOut()
        revoicer = FakeRevoicer(styled="Ahoy, past be due!")
>       sched = ReminderScheduler(
            store, tts, out, AudioArbiter(), poll_seconds=0.01, now=lambda: 100.0,
            revoicer=revoicer,
        )
E       TypeError: ReminderScheduler.__init__() got an unexpected keyword argument 'revoicer'

tests/test_scheduler.py:342: TypeError
_________________ test_catch_up_summary_revoiced_exactly_once __________________
...
E       TypeError: ReminderScheduler.__init__() got an unexpected keyword argument 'revoicer'
...
___________________ test_announcement_is_revoiced_before_tts ___________________
...
E       TypeError: CalendarWatcher.__init__() got an unexpected keyword argument 'revoicer'
...
___________ test_dedupe_unaffected_when_revoice_falls_back_to_plain ____________
...
E       TypeError: CalendarWatcher.__init__() got an unexpected keyword argument 'revoicer'

=========================== short test summary info ============================
FAILED tests/test_scheduler.py::test_due_reminder_is_revoiced_before_tts - Ty...
FAILED tests/test_scheduler.py::test_catch_up_summary_revoiced_exactly_once
FAILED tests/test_calendar_watcher.py::test_announcement_is_revoiced_before_tts
FAILED tests/test_calendar_watcher.py::test_dedupe_unaffected_when_revoice_falls_back_to_plain
========================= 4 failed, 26 passed in 0.71s =========================
```

All four new tests fail for the expected reason: `revoicer` is not yet an
accepted constructor keyword on `ReminderScheduler` / `CalendarWatcher`. The
26 pre-existing tests are unaffected (they don't pass `revoicer`).

### Post-implementation (passing)

Command:

```
source .venv/bin/activate && pytest tests/test_scheduler.py tests/test_calendar_watcher.py -v
```

Verbatim output (tail):

```
tests/test_calendar_watcher.py::test_moved_event_is_reannounced_with_new_time PASSED [ 60%]
tests/test_calendar_watcher.py::test_all_day_events_are_skipped PASSED   [ 63%]
tests/test_calendar_watcher.py::test_disabled_watcher_never_fetches PASSED [ 66%]
tests/test_calendar_watcher.py::test_voice_toggle_enables_the_running_loop PASSED [ 70%]
tests/test_calendar_watcher.py::test_provider_failure_survives_and_announces_next_poll PASSED [ 73%]
tests/test_calendar_watcher.py::test_speech_failure_is_retried_next_poll PASSED [ 76%]
tests/test_calendar_watcher.py::test_announcement_waits_for_arbiter PASSED [ 80%]
tests/test_calendar_watcher.py::test_imminent_event_says_now PASSED      [ 83%]
tests/test_calendar_watcher.py::test_standdown_skips_announcements PASSED [ 86%]
tests/test_calendar_watcher.py::test_announcement_is_revoiced_before_tts PASSED [ 90%]
tests/test_calendar_watcher.py::test_no_revoicer_is_byte_identical_to_today PASSED [ 93%]
tests/test_calendar_watcher.py::test_dedupe_unaffected_when_revoice_falls_back_to_plain PASSED [ 96%]
tests/test_calendar_watcher.py::test_blocked_event_is_not_announced_or_marked PASSED [100%]

============================== 30 passed in 0.70s ==============================
```

## AC-2

Due-reminder, catch-up (one call), and calendar announcements all pass
through the shared `Revoicer` before TTS.

- `assistant/scheduling/scheduler.py::ReminderScheduler._fire` — revoices
  `reminder.speech` before `self._tts.synthesize`, when `self._revoicer` is
  set. Pinned by `test_due_reminder_is_revoiced_before_tts`.
- `assistant/scheduling/scheduler.py::ReminderScheduler._fire_summary` —
  composes the preamble + joined reminder text first, then makes exactly
  **one** `revoice` call over that composed string before synthesis. Pinned
  by `test_catch_up_summary_revoiced_exactly_once`, which asserts
  `len(revoicer.calls) == 1` and that the single call's argument contains the
  full composed summary (preamble + both reminder bodies).
- `assistant/scheduling/calendar_watcher.py::CalendarWatcher._announce` —
  revoices the composed announcement text ("You have X in N minutes.")
  before synthesis. Pinned by `test_announcement_is_revoiced_before_tts`.
- `assistant/app.py` — the same `Revoicer` instance built for the pipeline
  (shared circuit state) is now passed to both `CalendarWatcher(...,
  revoicer=revoicer)` and `ReminderScheduler(..., revoicer=revoicer)`.

Command:

```
source .venv/bin/activate && pytest tests/test_scheduler.py::test_due_reminder_is_revoiced_before_tts tests/test_scheduler.py::test_catch_up_summary_revoiced_exactly_once tests/test_calendar_watcher.py::test_announcement_is_revoiced_before_tts -v
```

Output:

```
tests/test_scheduler.py::test_due_reminder_is_revoiced_before_tts PASSED [ 33%]
tests/test_scheduler.py::test_catch_up_summary_revoiced_exactly_once PASSED [ 66%]
tests/test_calendar_watcher.py::test_announcement_is_revoiced_before_tts PASSED [100%]

============================== 3 passed in 0.09s ==============================
```

## AC-3

With `revoicer=None` (the default) or a revoicer that falls back to plain
text (circuit open / failure), both schedulers' spoken output is
byte-identical to the pre-feather behavior, and dedupe/mark logic is
unaffected by a fallback.

- `test_no_revoicer_is_byte_identical_to_today` (scheduler) — no `revoicer`
  arg passed; asserts the catch-up summary text is exactly the old
  preamble + joined-reminders string, matching the pre-feather
  `test_boot_catch_up_coalesces_into_one_summary` assertions.
- `test_no_revoicer_is_byte_identical_to_today` (calendar watcher) — no
  `revoicer` arg passed; asserts `tts.spoke == ["You have Dentist in 10
  minutes."]`, matching pre-feather behavior.
- `test_dedupe_unaffected_when_revoice_falls_back_to_plain` — a
  `FallbackRevoicer` stub (mimics an open-circuit `Revoicer`: always returns
  the input text unchanged) is injected; asserts the event is spoken once
  and `state.was_announced(...)` is `True` after two polls, i.e. the mark
  step still runs and dedupe is unaffected by the fallback path.
- Bounded-by-timeout behavior (a failing revoice never delays an
  announcement beyond `revoice_timeout_s`) is inherited unchanged from
  `Revoicer.revoice`'s own `asyncio.wait_for(..., timeout=self._timeout)` and
  cooldown-circuit guard (`assistant/core/revoice.py`, unmodified by this
  feather) — the schedulers only call `await self._revoicer.revoice(text)`
  and never add their own timeout/retry around it, so `Revoicer`'s existing
  bound applies identically to both new call sites. This is the same
  reasoning FTHR-005 used for the pipeline's own `_speak` call site, which is
  covered by `tests/test_revoice.py`'s timeout and circuit tests.

Command:

```
source .venv/bin/activate && pytest tests/test_scheduler.py::test_no_revoicer_is_byte_identical_to_today tests/test_calendar_watcher.py::test_no_revoicer_is_byte_identical_to_today tests/test_calendar_watcher.py::test_dedupe_unaffected_when_revoice_falls_back_to_plain -v
```

Output:

```
tests/test_scheduler.py::test_no_revoicer_is_byte_identical_to_today PASSED [ 33%]
tests/test_calendar_watcher.py::test_no_revoicer_is_byte_identical_to_today PASSED [ 66%]
tests/test_calendar_watcher.py::test_dedupe_unaffected_when_revoice_falls_back_to_plain PASSED [100%]

============================== 3 passed in 0.08s ==============================
```

## AC-4

`ruff check assistant tests` and the full suite pass without native extras
or network.

Note: in this worktree's fresh venv, `pip install -e ".[dev]"` alone left
several test modules unable to import (`webrtcvad`/`httpx`-dependent modules
erroring at collection) — a pre-existing packaging gap unrelated to this
feather, per the assignment's guidance. Installed
`pip install -e ".[dev,all,tui]"` instead, which resolved it; all 823 tests
then ran successfully offline.

Commands:

```
source .venv/bin/activate && ruff check assistant tests
source .venv/bin/activate && pytest
```

Output:

```
All checks passed!
```

```
================== 823 passed, 2 skipped, 1 warning in 20.87s ==================
```

(The 2 skipped and the `pkg_resources` deprecation warning are pre-existing
and unrelated to this feather.)
