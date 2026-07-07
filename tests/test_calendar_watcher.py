import asyncio
from datetime import datetime, timedelta, timezone

from assistant.calendar.base import CalendarEvent
from assistant.calendar.blocklist import EventBlocklist
from assistant.core.arbiter import AudioArbiter
from assistant.scheduling.calendar_watcher import CalendarWatcher
from assistant.storage.calendar_state import CalendarStateStore

TZ = timezone(timedelta(hours=-4))
NOW = datetime(2026, 7, 6, 10, 0, tzinfo=TZ)
CAL = "cal@group.calendar.google.com"


def _event(id_, title, start, *, all_day=False):
    return CalendarEvent(
        id=id_, calendar_id=CAL, title=title, start=start,
        end=start + timedelta(hours=1), all_day=all_day,
    )


class FakeProvider:
    def __init__(self, events=()):
        self.events = list(events)
        self.calls = 0
        self.fail_first = False

    async def list_events(self, calendar_id, *, time_min, time_max, max_results=50):
        self.calls += 1
        if self.fail_first:
            self.fail_first = False
            raise RuntimeError("network down")
        return [e for e in self.events if time_min <= e.start < time_max]


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


def _watcher(provider, state, tts=None, out=None, *, enabled=True, now=lambda: NOW, **kw):
    kw.setdefault("blocklist", EventBlocklist(state, config_patterns=[]))
    return CalendarWatcher(
        provider, state, tts or FakeTTS(), out or FakeOut(), AudioArbiter(),
        calendar_ids=[CAL], poll_seconds=0.01, lead_minutes=15,
        enabled=enabled, now=now, **kw,
    )


async def _run_polls(watcher, n=1):
    for _ in range(n):
        await watcher._poll()


async def test_announces_event_in_lead_window_with_minutes(tmp_path):
    state = CalendarStateStore(str(tmp_path / "s.db"))
    tts = FakeTTS()
    provider = FakeProvider([
        _event("ev1", "Dentist", NOW + timedelta(minutes=10)),
        _event("far", "Later", NOW + timedelta(hours=3)),  # outside the window
    ])
    await _run_polls(_watcher(provider, state, tts))
    assert tts.spoke == ["You have Dentist in 10 minutes."]
    state.close()


async def test_never_reannounces_on_later_polls(tmp_path):
    state = CalendarStateStore(str(tmp_path / "s.db"))
    tts = FakeTTS()
    provider = FakeProvider([_event("ev1", "Dentist", NOW + timedelta(minutes=10))])
    await _run_polls(_watcher(provider, state, tts), n=3)
    assert tts.spoke == ["You have Dentist in 10 minutes."]
    state.close()


async def test_dedupe_survives_restart(tmp_path):
    db = str(tmp_path / "s.db")
    provider = FakeProvider([_event("ev1", "Dentist", NOW + timedelta(minutes=10))])

    first_state, first_tts = CalendarStateStore(db), FakeTTS()
    await _run_polls(_watcher(provider, first_state, first_tts))
    assert len(first_tts.spoke) == 1
    first_state.close()

    second_state, second_tts = CalendarStateStore(db), FakeTTS()  # daemon restart
    await _run_polls(_watcher(provider, second_state, second_tts))
    assert second_tts.spoke == []
    second_state.close()


async def test_moved_event_is_reannounced_with_new_time(tmp_path):
    state = CalendarStateStore(str(tmp_path / "s.db"))
    tts = FakeTTS()
    provider = FakeProvider([_event("ev1", "Dentist", NOW + timedelta(minutes=5))])
    watcher = _watcher(provider, state, tts)
    await _run_polls(watcher)
    provider.events = [_event("ev1", "Dentist", NOW + timedelta(minutes=12))]  # rescheduled
    await _run_polls(watcher)
    assert tts.spoke == [
        "You have Dentist in 5 minutes.",
        "You have Dentist in 12 minutes.",
    ]
    state.close()


async def test_all_day_events_are_skipped(tmp_path):
    state = CalendarStateStore(str(tmp_path / "s.db"))
    tts = FakeTTS()
    provider = FakeProvider([_event("ev1", "Conference", NOW + timedelta(minutes=5), all_day=True)])
    await _run_polls(_watcher(provider, state, tts))
    assert tts.spoke == []
    state.close()


async def test_disabled_watcher_never_fetches(tmp_path):
    state = CalendarStateStore(str(tmp_path / "s.db"))
    provider = FakeProvider([_event("ev1", "Dentist", NOW + timedelta(minutes=5))])
    watcher = _watcher(provider, state, enabled=False)

    task = asyncio.create_task(watcher.run())
    await asyncio.sleep(0.05)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    assert provider.calls == 0
    state.close()


async def test_voice_toggle_enables_the_running_loop(tmp_path):
    state = CalendarStateStore(str(tmp_path / "s.db"))
    tts = FakeTTS()
    provider = FakeProvider([_event("ev1", "Dentist", NOW + timedelta(minutes=5))])
    watcher = _watcher(provider, state, tts, enabled=False)

    task = asyncio.create_task(watcher.run())
    await asyncio.sleep(0.03)
    assert tts.spoke == []
    watcher.enabled = True  # what the skill's toggle does
    for _ in range(20):
        if tts.spoke:
            break
        await asyncio.sleep(0.02)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    assert tts.spoke == ["You have Dentist in 5 minutes."]
    state.close()


async def test_provider_failure_survives_and_announces_next_poll(tmp_path):
    state = CalendarStateStore(str(tmp_path / "s.db"))
    tts = FakeTTS()
    provider = FakeProvider([_event("ev1", "Dentist", NOW + timedelta(minutes=5))])
    provider.fail_first = True
    watcher = _watcher(provider, state, tts)

    task = asyncio.create_task(watcher.run())
    for _ in range(20):
        if tts.spoke:
            break
        await asyncio.sleep(0.02)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    assert tts.spoke == ["You have Dentist in 5 minutes."]
    state.close()


async def test_speech_failure_is_retried_next_poll(tmp_path):
    state = CalendarStateStore(str(tmp_path / "s.db"))
    provider = FakeProvider([_event("ev1", "Dentist", NOW + timedelta(minutes=5))])

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

    tts = FlakyTTS()
    watcher = _watcher(provider, state, tts)
    await _run_polls(watcher)  # synthesize raises -> not marked
    assert tts.spoke == []
    assert not state.was_announced("ev1", (NOW + timedelta(minutes=5)).timestamp())
    await _run_polls(watcher)  # retried and marked
    assert tts.spoke == ["You have Dentist in 5 minutes."]
    state.close()


async def test_announcement_waits_for_arbiter(tmp_path):
    state = CalendarStateStore(str(tmp_path / "s.db"))
    tts, out, arbiter = FakeTTS(), FakeOut(), AudioArbiter()
    provider = FakeProvider([_event("ev1", "Dentist", NOW + timedelta(minutes=5))])
    watcher = CalendarWatcher(
        provider, state, tts, out, arbiter,
        blocklist=EventBlocklist(state, config_patterns=[]),
        calendar_ids=[CAL], poll_seconds=0.01, lead_minutes=15, now=lambda: NOW,
    )

    async with arbiter.hold("pipeline"):
        task = asyncio.create_task(watcher.run())
        await asyncio.sleep(0.05)
        assert out.played == []  # blocked: the pipeline holds the audio

    for _ in range(20):
        if out.played:
            break
        await asyncio.sleep(0.02)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    assert out.played == [b"You have Dentist in 5 minutes."]
    state.close()


async def test_imminent_event_says_now(tmp_path):
    state = CalendarStateStore(str(tmp_path / "s.db"))
    tts = FakeTTS()
    provider = FakeProvider([_event("ev1", "Dentist", NOW + timedelta(seconds=10))])
    await _run_polls(_watcher(provider, state, tts))
    assert tts.spoke == ["You have Dentist now."]
    state.close()


async def test_standdown_skips_announcements(tmp_path):
    # While standing down the watcher never fetches; resume -> announced.
    from assistant.core.standdown import StandDown

    state = CalendarStateStore(str(tmp_path / "s.db"))
    tts = FakeTTS()
    provider = FakeProvider([_event("ev1", "Dentist", NOW + timedelta(minutes=5))])
    standdown = StandDown()
    standdown.engage(None)
    watcher = _watcher(provider, state, tts, standdown=standdown)

    task = asyncio.create_task(watcher.run())
    await asyncio.sleep(0.05)
    assert provider.calls == 0  # never fetched while standing down
    assert tts.spoke == []

    standdown.resume()
    for _ in range(20):
        if tts.spoke:
            break
        await asyncio.sleep(0.02)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    assert tts.spoke == ["You have Dentist in 5 minutes."]
    state.close()


async def test_blocked_event_is_not_announced_or_marked(tmp_path):
    state = CalendarStateStore(str(tmp_path / "s.db"))
    tts = FakeTTS()
    provider = FakeProvider([
        _event("ev1", "🛏️ Bedtime", NOW + timedelta(minutes=5)),
        _event("ev2", "Dentist", NOW + timedelta(minutes=10)),
    ])
    blocklist = EventBlocklist(state, config_patterns=["bedtime"])
    await _run_polls(_watcher(provider, state, tts, blocklist=blocklist))
    assert tts.spoke == ["You have Dentist in 10 minutes."]
    assert not state.was_announced("ev1", (NOW + timedelta(minutes=5)).timestamp())
    state.close()
