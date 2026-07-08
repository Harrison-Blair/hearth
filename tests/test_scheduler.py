import asyncio

from assistant.core.arbiter import AudioArbiter
from assistant.scheduling.scheduler import ReminderScheduler
from assistant.storage.reminders import ReminderStore


class FakeTTS:
    def __init__(self):
        self.spoke = []

    async def synthesize(self, text):
        self.spoke.append(text)
        return text.encode()


class FakeOut:
    def __init__(self):
        self.played = []

    async def play(self, audio):
        self.played.append(audio)


class FakeRevoicer:
    """Records the plain text it was asked to restyle and returns a fixed reply."""

    def __init__(self, styled="STYLED"):
        self.styled = styled
        self.calls = []

    async def revoice(self, text):
        self.calls.append(text)
        return self.styled


async def _run_until(predicate, *, tries=20, delay=0.02):
    for _ in range(tries):
        if predicate():
            return
        await asyncio.sleep(delay)


async def test_fires_due_deletes_and_skips_future():
    store = ReminderStore(":memory:")
    store.add(50.0, "past", created_at=0.0)
    store.add(500.0, "future", created_at=0.0)
    tts, out = FakeTTS(), FakeOut()
    sched = ReminderScheduler(
        store, tts, out, AudioArbiter(), poll_seconds=0.01, now=lambda: 100.0
    )

    task = asyncio.create_task(sched.run())
    await _run_until(lambda: out.played)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    assert tts.spoke == ["past"]          # only the due one
    assert out.played == [b"past"]
    assert store.due(now=100.0) == []     # deleted, not re-fired
    store.close()


async def test_transient_failure_retries_then_speaks():
    # A transient TTS error must not lose the reminder: it survives the failed poll
    # and is spoken (then deleted) on the retry.
    store = ReminderStore(":memory:")
    store.add(50.0, "boom-once", created_at=0.0)

    class FlakyTTS:
        def __init__(self):
            self.calls = 0
            self.spoke = []

        async def synthesize(self, text):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("tts busy")
            self.spoke.append(text)
            return text.encode()

    tts, out = FlakyTTS(), FakeOut()
    sched = ReminderScheduler(
        store, tts, out, AudioArbiter(), poll_seconds=0.01, now=lambda: 100.0
    )

    # First poll: synthesize raises -> the row survives for a retry.
    await sched._fire(store.due(now=100.0)[0])
    assert store.due(now=100.0) != []
    assert out.played == []

    # Second poll: synthesize succeeds -> spoken and deleted.
    await sched._fire(store.due(now=100.0)[0])
    assert tts.spoke == ["boom-once"]
    assert out.played == [b"boom-once"]
    assert store.due(now=100.0) == []
    store.close()


class BoomOut:
    async def play(self, audio):
        raise RuntimeError("audio device gone")


async def test_permanent_failure_defers_instead_of_deleting():
    # An un-speakable reminder is deferred after exactly max_attempts polls, not
    # deleted: a failure to *speak* must never destroy the reminder, but pushing
    # due_at forward keeps it from looping on every poll.
    store = ReminderStore(":memory:")
    rid = store.add(50.0, "always-boom", created_at=0.0)
    tts = FakeTTS()

    sched = ReminderScheduler(
        store, tts, BoomOut(), AudioArbiter(), poll_seconds=0.01, max_attempts=3, now=lambda: 100.0
    )

    for _ in range(2):
        await sched._fire(store.due(now=100.0)[0])
        assert store.due(now=100.0) != []  # still present before the budget is spent

    await sched._fire(store.due(now=100.0)[0])  # third attempt reaches max_attempts
    assert store.due(now=100.0) == []  # no longer immediately due: no tight loop
    (deferred,) = store.pending(now=100.0)  # but the row survives
    assert deferred.id == rid
    assert deferred.due_at == 160.0  # 100 (now) + 60 (defer window)
    assert rid not in sched._attempts  # budget reset for the next window
    store.close()


async def test_recurring_reminder_survives_exhausted_retries():
    # A recurring reminder mid-conversation (audio held elsewhere) must survive
    # the exhausted retry budget with its cadence intact.
    store = ReminderStore(":memory:")
    rid = store.add(50.0, "Reminder: stretch.", created_at=0.0, interval=900.0)
    tts = FakeTTS()

    sched = ReminderScheduler(
        store, tts, BoomOut(), AudioArbiter(), poll_seconds=0.01, max_attempts=3, now=lambda: 100.0
    )

    for _ in range(3):
        await sched._fire(store.due(now=100.0)[0])

    (deferred,) = store.pending(now=100.0)
    assert deferred.id == rid
    assert deferred.interval == 900.0
    assert deferred.due_at == 160.0  # deferred, not deleted or re-armed a full interval
    store.close()


async def test_recurring_reminder_rearms_instead_of_deleting():
    store = ReminderStore(":memory:")
    rid = store.add(50.0, "Reminder: stretch.", created_at=0.0, interval=900.0)
    tts, out = FakeTTS(), FakeOut()
    sched = ReminderScheduler(
        store, tts, out, AudioArbiter(), poll_seconds=0.01, now=lambda: 100.0
    )

    await sched._fire(store.due(now=100.0)[0])

    assert tts.spoke == ["Reminder: stretch."]
    # Row survives, re-armed to now + interval (not deleted, not replaying missed slots).
    (rearmed,) = store.pending(now=100.0)
    assert rearmed.id == rid
    assert rearmed.due_at == 1000.0  # 100 (now) + 900 (interval)
    assert store.due(now=100.0) == []  # no longer due until 1000
    store.close()


async def test_catch_up_rearms_recurring_deletes_oneshot():
    store = ReminderStore(":memory:")
    store.add(10.0, "Reminder: stretch.", created_at=0.0, interval=900.0)
    store.add(20.0, "Reminder: call mom.", created_at=0.0)  # one-shot
    tts, out = FakeTTS(), FakeOut()
    sched = ReminderScheduler(
        store, tts, out, AudioArbiter(), poll_seconds=0.01, now=lambda: 100.0
    )

    task = asyncio.create_task(sched.run())
    await _run_until(lambda: out.played)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    # One-shot is gone; recurring survives, re-armed to the future.
    remaining = {r.speech: r.due_at for r in store.pending(now=100.0)}
    assert remaining == {"Reminder: stretch.": 1000.0}
    store.close()


async def test_boot_catch_up_coalesces_into_one_summary():
    store = ReminderStore(":memory:")
    store.add(10.0, "Reminder: call mom.", created_at=0.0)
    store.add(20.0, "Your timer is done.", created_at=0.0)
    tts, out = FakeTTS(), FakeOut()
    sched = ReminderScheduler(
        store, tts, out, AudioArbiter(), poll_seconds=0.01, now=lambda: 100.0
    )

    task = asyncio.create_task(sched.run())
    await _run_until(lambda: out.played)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    assert len(out.played) == 1  # one combined announcement, not two
    summary = tts.spoke[0]
    assert summary.startswith("While I was away, 2 reminders came due.")
    assert "Reminder: call mom." in summary
    assert "Your timer is done." in summary
    assert store.due(now=100.0) == []  # all deleted
    store.close()


async def test_steady_state_fires_individually_not_summarized():
    # First poll sees nothing due (flips _first_poll); a later poll sees two newly
    # due reminders and must fire them one-by-one, with no catch-up preamble.
    store = ReminderStore(":memory:")
    store.add(150.0, "r1", created_at=0.0)
    store.add(160.0, "r2", created_at=0.0)
    clock = iter([100.0])  # first poll: nothing due yet

    def now():
        return next(clock, 200.0)  # subsequent polls: both are due

    tts, out = FakeTTS(), FakeOut()
    sched = ReminderScheduler(store, tts, out, AudioArbiter(), poll_seconds=0.01, now=now)

    task = asyncio.create_task(sched.run())
    await _run_until(lambda: len(out.played) == 2)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    assert tts.spoke == ["r1", "r2"]  # individual, no "While I was away" preamble
    store.close()


async def test_announcement_waits_for_arbiter():
    store = ReminderStore(":memory:")
    store.add(50.0, "hi", created_at=0.0)
    tts, out, arbiter = FakeTTS(), FakeOut(), AudioArbiter()
    sched = ReminderScheduler(
        store, tts, out, arbiter, poll_seconds=0.01, now=lambda: 100.0
    )

    async with arbiter.hold("pipeline"):
        task = asyncio.create_task(sched.run())
        await asyncio.sleep(0.05)
        assert out.played == []  # blocked: the pipeline holds the audio

    await _run_until(lambda: out.played)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    assert out.played == [b"hi"]
    store.close()


async def test_standdown_delays_reminders_until_resume():
    # While standing down the poll is skipped: nothing plays and the row survives.
    # Resume -> the next poll fires and deletes it via the existing machinery.
    from assistant.core.standdown import StandDown

    store = ReminderStore(":memory:")
    store.add(50.0, "delayed", created_at=0.0)
    tts, out = FakeTTS(), FakeOut()
    standdown = StandDown()
    standdown.engage(None)
    sched = ReminderScheduler(
        store, tts, out, AudioArbiter(), poll_seconds=0.01, now=lambda: 100.0,
        standdown=standdown,
    )

    task = asyncio.create_task(sched.run())
    await asyncio.sleep(0.05)
    assert out.played == []               # silenced while standing down
    assert store.due(now=100.0) != []     # not lost

    standdown.resume()
    await _run_until(lambda: out.played)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    assert tts.spoke == ["delayed"]
    assert store.due(now=100.0) == []     # fired and deleted after resume
    store.close()


async def test_standdown_preserves_boot_catchup():
    # Paused polls must not consume the first-poll flag: after resume, a multi-
    # reminder backlog still coalesces into one "while I was away" summary.
    from assistant.core.standdown import StandDown

    store = ReminderStore(":memory:")
    store.add(10.0, "r1", created_at=0.0)
    store.add(20.0, "r2", created_at=0.0)
    tts, out = FakeTTS(), FakeOut()
    standdown = StandDown()
    standdown.engage(None)
    sched = ReminderScheduler(
        store, tts, out, AudioArbiter(), poll_seconds=0.01, now=lambda: 100.0,
        standdown=standdown,
    )

    task = asyncio.create_task(sched.run())
    await asyncio.sleep(0.05)  # several paused polls tick by
    assert out.played == []    # backlog held, nothing spoken while standing down
    standdown.resume()
    await _run_until(lambda: out.played)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    assert len(out.played) == 1  # one combined announcement, not two
    assert tts.spoke[0].startswith("While I was away, 2 reminders came due.")
    store.close()


async def test_due_reminder_is_revoiced_before_tts():
    store = ReminderStore(":memory:")
    store.add(50.0, "past", created_at=0.0)
    tts, out = FakeTTS(), FakeOut()
    revoicer = FakeRevoicer(styled="Ahoy, past be due!")
    sched = ReminderScheduler(
        store, tts, out, AudioArbiter(), poll_seconds=0.01, now=lambda: 100.0,
        revoicer=revoicer,
    )

    task = asyncio.create_task(sched.run())
    await _run_until(lambda: out.played)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    assert revoicer.calls == ["past"]
    assert tts.spoke == ["Ahoy, past be due!"]
    assert out.played == [b"Ahoy, past be due!"]
    store.close()


async def test_catch_up_summary_revoiced_exactly_once():
    store = ReminderStore(":memory:")
    store.add(10.0, "Reminder: call mom.", created_at=0.0)
    store.add(20.0, "Your timer is done.", created_at=0.0)
    tts, out = FakeTTS(), FakeOut()
    revoicer = FakeRevoicer(styled="Ahoy, ye missed two reminders!")
    sched = ReminderScheduler(
        store, tts, out, AudioArbiter(), poll_seconds=0.01, now=lambda: 100.0,
        revoicer=revoicer,
    )

    task = asyncio.create_task(sched.run())
    await _run_until(lambda: out.played)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    # Exactly one revoice call over the composed summary, not one per reminder.
    assert len(revoicer.calls) == 1
    composed = revoicer.calls[0]
    assert composed.startswith("While I was away, 2 reminders came due.")
    assert "Reminder: call mom." in composed
    assert "Your timer is done." in composed
    assert tts.spoke == ["Ahoy, ye missed two reminders!"]
    store.close()


async def test_no_revoicer_is_byte_identical_to_today():
    # revoicer=None must keep spoken output exactly what it was before this feather.
    store = ReminderStore(":memory:")
    store.add(10.0, "Reminder: call mom.", created_at=0.0)
    store.add(20.0, "Your timer is done.", created_at=0.0)
    tts, out = FakeTTS(), FakeOut()
    sched = ReminderScheduler(
        store, tts, out, AudioArbiter(), poll_seconds=0.01, now=lambda: 100.0,
    )

    task = asyncio.create_task(sched.run())
    await _run_until(lambda: out.played)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    assert len(out.played) == 1
    summary = tts.spoke[0]
    assert summary.startswith("While I was away, 2 reminders came due.")
    assert "Reminder: call mom." in summary
    assert "Your timer is done." in summary
    store.close()
