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


async def test_fires_due_marks_fired_and_skips_future():
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
    assert store.due(now=100.0) == []     # marked fired, not re-fired
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
