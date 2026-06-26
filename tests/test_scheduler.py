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


async def test_failed_announcement_still_deletes_no_refire():
    # If play raises, the reminder must still be removed: a row left in the store
    # is returned by every poll, an unkillable re-fire loop.
    store = ReminderStore(":memory:")
    store.add(50.0, "boom", created_at=0.0)
    tts = FakeTTS()

    class BoomOut:
        async def play(self, audio):
            raise RuntimeError("audio device gone")

    sched = ReminderScheduler(
        store, tts, BoomOut(), AudioArbiter(), poll_seconds=0.01, now=lambda: 100.0
    )

    task = asyncio.create_task(sched.run())
    await _run_until(lambda: store.due(now=100.0) == [])
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    assert store.due(now=100.0) == []  # deleted despite the playback failure
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
