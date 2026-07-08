from datetime import datetime, timedelta, timezone

from assistant.calendar.base import CalendarEvent
from assistant.calendar.blocklist import EventBlocklist
from assistant.core.events import Command, Intent
from assistant.skills.calendar import CalendarSkill
from assistant.storage.calendar_state import CalendarStateStore
from assistant.storage.reminders import ReminderStore

TZ = timezone(timedelta(hours=-4))
NOW = datetime(2026, 7, 6, 10, 0, tzinfo=TZ)  # Monday 10:00
PERSONAL = "me@example.com"
CALCIFER = "calcifer@group.calendar.google.com"


def _event(id_, title, start, *, calendar_id=PERSONAL, all_day=False, hours=1):
    return CalendarEvent(
        id=id_, calendar_id=calendar_id, title=title, start=start,
        end=start + timedelta(hours=hours), all_day=all_day,
    )


class FakeProvider:
    def __init__(self, events=()):
        self.events = list(events)
        self.listed: list[str] = []
        self.created: list[dict] = []
        self.updated: list[dict] = []
        self.deleted: list[tuple[str, str]] = []
        self.raises = False

    async def list_events(self, calendar_id, *, time_min, time_max, max_results=50):
        if self.raises:
            raise RuntimeError("network down")
        self.listed.append(calendar_id)
        return [
            e for e in self.events
            if e.calendar_id == calendar_id and time_min <= e.start < time_max
        ]

    async def create_event(self, calendar_id, *, title, start, end):
        if self.raises:
            raise RuntimeError("network down")
        event = CalendarEvent(id="new1", calendar_id=calendar_id, title=title, start=start, end=end)
        self.created.append({"calendar_id": calendar_id, "title": title, "start": start, "end": end})
        return event

    async def update_event(self, calendar_id, event_id, *, title=None, start=None, end=None):
        self.updated.append(
            {"calendar_id": calendar_id, "event_id": event_id,
             "title": title, "start": start, "end": end}
        )
        return _event(event_id, title or "x", start or NOW, calendar_id=calendar_id)

    async def delete_event(self, calendar_id, event_id):
        self.deleted.append((calendar_id, event_id))

    async def health(self):
        return True


class FakeLLM:
    def __init__(self, reply: str = "{}"):
        self.reply = reply
        self.prompts: list[str] = []

    async def complete(self, prompt, json=False, label=None):
        self.prompts.append(prompt)
        return self.reply


class StubWatcher:
    enabled = False


def _blocklist(config_patterns=()):
    return EventBlocklist(
        CalendarStateStore(":memory:"), config_patterns=list(config_patterns)
    )


def _skill(provider, llm=None, store=None, watcher=None, blocklist=None):
    return CalendarSkill(
        provider,
        llm or FakeLLM(),
        store if store is not None else ReminderStore(":memory:"),
        watcher or StubWatcher(),
        blocklist=blocklist or _blocklist(),
        personal_id=PERSONAL,
        calcifer_id=CALCIFER,
        now=lambda: NOW,
    )


# -- query ------------------------------------------------------------------


async def test_query_today_merges_both_calendars_in_start_order():
    provider = FakeProvider([
        _event("p1", "Gym", NOW.replace(hour=15), calendar_id=PERSONAL),
        _event("c1", "Dentist", NOW.replace(hour=12), calendar_id=CALCIFER),
    ])
    res = await _skill(provider).handle(Command("calendar"), Intent("calendar_query", slots={"day": "today"}))
    assert res.speech == "You have 2 events today: Dentist at 12 PM, and Gym at 3 PM."
    assert provider.listed == [PERSONAL, CALCIFER]


async def test_query_empty_day():
    res = await _skill(FakeProvider()).handle(
        Command("calendar"), Intent("calendar_query", slots={"day": "tomorrow"})
    )
    assert res.speech == "Nothing on your calendar tomorrow."


async def test_query_default_week_includes_day_names_and_all_day():
    provider = FakeProvider([
        _event("p1", "Conference", NOW + timedelta(days=2), all_day=True),
    ])
    res = await _skill(provider).handle(Command("calendar"), Intent("calendar_query"))
    assert res.speech == "You have 1 event in the next 7 days: Conference on Wednesday all day."


async def test_query_strips_emoji_from_titles():
    provider = FakeProvider([_event("p1", "🏋️ Gym", NOW.replace(hour=15))])
    res = await _skill(provider).handle(
        Command("calendar"), Intent("calendar_query", slots={"day": "today"})
    )
    assert "🏋" not in res.speech
    assert "Gym at 3 PM" in res.speech


async def test_query_caps_spoken_events():
    events = [
        _event(f"p{i}", f"Event {i}", NOW.replace(hour=11) + timedelta(minutes=i))
        for i in range(12)
    ]
    res = await _skill(FakeProvider(events)).handle(
        Command("calendar"), Intent("calendar_query", slots={"day": "today"})
    )
    assert res.speech.startswith("You have 12 events today:")
    assert res.speech.endswith(", and 4 more.")


async def test_query_provider_failure_degrades_to_speech():
    provider = FakeProvider()
    provider.raises = True
    res = await _skill(provider).handle(Command("calendar"), Intent("calendar_query"))
    assert res.speech == "Sorry, I can't reach your calendar right now."
    assert not res.success


# -- blocked events -----------------------------------------------------------


async def test_query_hides_blocked_events_from_count_and_listing():
    provider = FakeProvider([
        _event("p1", "🛏️ Bedtime", NOW.replace(hour=22)),
        _event("p2", "Gym", NOW.replace(hour=15)),
    ])
    res = await _skill(provider, blocklist=_blocklist(["bedtime"])).handle(
        Command("calendar"), Intent("calendar_query", slots={"day": "today"})
    )
    assert res.speech == "You have 1 event today: Gym at 3 PM."


async def test_query_with_everything_blocked_reads_as_empty():
    provider = FakeProvider([_event("p1", "Wake up", NOW.replace(hour=11))])
    res = await _skill(provider, blocklist=_blocklist(["wake up"])).handle(
        Command("calendar"), Intent("calendar_query", slots={"day": "today"})
    )
    assert res.speech == "Nothing on your calendar today."


async def test_query_hides_events_tagged_hidden_in_description():
    tagged = _event("p1", "Dentist", NOW.replace(hour=15))
    tagged.description = "routine [hidden] visit"
    provider = FakeProvider([tagged, _event("p2", "Gym", NOW.replace(hour=16))])
    res = await _skill(provider).handle(
        Command("calendar"), Intent("calendar_query", slots={"day": "today"})
    )
    assert res.speech == "You have 1 event today: Gym at 4 PM."


async def test_event_reminder_still_finds_blocked_events():
    store = ReminderStore(":memory:")
    provider = FakeProvider([
        _event("p1", "Wake up", NOW + timedelta(hours=3)),
    ])
    llm = FakeLLM('{"target_index": 1, "lead_minutes": 30}')
    res = await _skill(
        provider, llm=llm, store=store, blocklist=_blocklist(["wake up"])
    ).handle(
        Command("remind me 30 minutes before wake up"), Intent("calendar_event_reminder")
    )
    assert res.success
    assert len(store.pending(NOW.timestamp())) == 1


# -- repeat collapsing ---------------------------------------------------------


def _bedtimes(days=6):
    return [
        _event(f"b{i}", "Bedtime", NOW.replace(hour=22) + timedelta(days=i))
        for i in range(days)
    ]


async def test_week_query_collapses_repeated_events():
    provider = FakeProvider(
        _bedtimes(6) + [_event("p1", "Gym", (NOW + timedelta(days=1)).replace(hour=17))]
    )
    res = await _skill(provider).handle(Command("calendar"), Intent("calendar_query"))
    assert res.speech == (
        "You have 7 events in the next 7 days: "
        "Bedtime at 10 PM on 6 days, and Gym tomorrow at 5 PM."
    )


async def test_collapse_with_mixed_times_omits_the_time():
    events = [
        _event(f"s{i}", "Standup", (NOW + timedelta(days=i)).replace(hour=11 + i))
        for i in range(3)
    ]
    res = await _skill(FakeProvider(events)).handle(
        Command("calendar"), Intent("calendar_query")
    )
    assert res.speech == "You have 3 events in the next 7 days: Standup on 3 days."


async def test_two_repeats_are_not_collapsed():
    events = [
        _event("d1", "Dentist", (NOW + timedelta(days=1)).replace(hour=15)),
        _event("d2", "Dentist", (NOW + timedelta(days=3)).replace(hour=15)),
    ]
    res = await _skill(FakeProvider(events)).handle(
        Command("calendar"), Intent("calendar_query")
    )
    assert res.speech == (
        "You have 2 events in the next 7 days: "
        "Dentist tomorrow at 3 PM, and Dentist on Thursday at 3 PM."
    )


async def test_single_day_query_never_collapses():
    events = [
        _event(f"m{i}", "Meds", NOW.replace(hour=11 + 2 * i)) for i in range(3)
    ]
    res = await _skill(FakeProvider(events)).handle(
        Command("calendar"), Intent("calendar_query", slots={"day": "today"})
    )
    assert res.speech.count("Meds") == 3


async def test_spoken_cap_counts_a_collapsed_group_as_one_item():
    fillers = [
        _event(f"f{i}", f"Task {i}", (NOW + timedelta(days=1)).replace(hour=8 + i))
        for i in range(9)
    ]
    res = await _skill(FakeProvider(_bedtimes(6) + fillers)).handle(
        Command("calendar"), Intent("calendar_query")
    )
    assert res.speech.startswith("You have 15 events in the next 7 days:")
    assert "Bedtime at 10 PM on 6 days" in res.speech
    assert res.speech.endswith(", and 2 more.")


# -- create -------------------------------------------------------------------


async def test_create_writes_to_calcifer_calendar():
    llm = FakeLLM(
        '{"title": "dentist appointment", "date": "2026-07-07", '
        '"start_time": "15:00", "duration_minutes": null}'
    )
    provider = FakeProvider()
    res = await _skill(provider, llm=llm).handle(
        Command("add a dentist appointment tuesday at 3"), Intent("calendar_create")
    )
    (created,) = provider.created
    assert created["calendar_id"] == CALCIFER
    assert created["start"] == datetime(2026, 7, 7, 15, 0, tzinfo=TZ)
    assert created["end"] == datetime(2026, 7, 7, 16, 0, tzinfo=TZ)
    assert res.speech == "Okay, dentist appointment tomorrow at 3 PM for 1 hour."


async def test_create_unparseable_request_apologizes():
    res = await _skill(FakeProvider(), llm=FakeLLM("not json")).handle(
        Command("make an event"), Intent("calendar_create")
    )
    assert not res.success
    assert res.speech == "Sorry, I didn't catch the event's name or time."


# -- manage -------------------------------------------------------------------


def _calcifer_events():
    return [
        _event("c1", "Dentist", NOW + timedelta(days=1), calendar_id=CALCIFER),
        _event("c2", "Lunch", NOW + timedelta(days=2), calendar_id=CALCIFER),
    ]


async def test_manage_lists_only_calcifer_events():
    provider = FakeProvider(
        _calcifer_events() + [_event("p1", "Private thing", NOW + timedelta(days=1))]
    )
    llm = FakeLLM('{"action": "cancel", "target_index": 1}')
    await _skill(provider, llm=llm).handle(Command("cancel the dentist"), Intent("calendar_manage"))
    assert provider.listed == [CALCIFER]
    assert "Private thing" not in llm.prompts[0]


async def test_manage_cancel_deletes_target():
    provider = FakeProvider(_calcifer_events())
    llm = FakeLLM('{"action": "cancel", "target_index": 2}')
    res = await _skill(provider, llm=llm).handle(Command("cancel lunch"), Intent("calendar_manage"))
    assert provider.deleted == [(CALCIFER, "c2")]
    assert res.speech == "Okay, I've cancelled Lunch."


async def test_manage_reschedule_keeps_duration():
    provider = FakeProvider(_calcifer_events())
    llm = FakeLLM(
        '{"action": "reschedule", "target_index": 1, "new_date": null, "new_start_time": "16:00"}'
    )
    res = await _skill(provider, llm=llm).handle(
        Command("move the dentist to 4"), Intent("calendar_manage")
    )
    (updated,) = provider.updated
    assert updated["event_id"] == "c1"
    assert updated["start"] == (NOW + timedelta(days=1)).replace(
        hour=16, minute=0, second=0, microsecond=0
    )
    assert updated["end"] - updated["start"] == timedelta(hours=1)
    assert res.speech == "Okay, I've moved Dentist to tomorrow at 4 PM."


async def test_manage_reschedule_bare_time_keeps_the_events_date():
    # "move the dentist to 4 pm" on a tomorrow-event must stay tomorrow, not
    # jump to today (resolve_start's null-date default).
    provider = FakeProvider(_calcifer_events())  # c1 is tomorrow at 10:00
    llm = FakeLLM(
        '{"action": "reschedule", "target_index": 1, "new_date": null, "new_start_time": "16:00"}'
    )
    await _skill(provider, llm=llm).handle(Command("move the dentist to 4"), Intent("calendar_manage"))
    (updated,) = provider.updated
    assert updated["start"] == (NOW + timedelta(days=1)).replace(hour=16, minute=0, second=0, microsecond=0)


async def test_manage_reschedule_to_earlier_time_stays_on_the_same_day():
    provider = FakeProvider(_calcifer_events())  # c1 is tomorrow at 10:00
    llm = FakeLLM(
        '{"action": "reschedule", "target_index": 1, "new_date": null, "new_start_time": "08:00"}'
    )
    await _skill(provider, llm=llm).handle(Command("move it to 8 am"), Intent("calendar_manage"))
    (updated,) = provider.updated
    assert updated["start"] == (NOW + timedelta(days=1)).replace(
        hour=8, minute=0, second=0, microsecond=0
    )


async def test_manage_rename():
    provider = FakeProvider(_calcifer_events())
    llm = FakeLLM('{"action": "rename", "target_index": 1, "new_title": "Orthodontist"}')
    res = await _skill(provider, llm=llm).handle(
        Command("rename the dentist thing"), Intent("calendar_manage")
    )
    (updated,) = provider.updated
    assert updated["title"] == "Orthodontist"
    assert res.speech == "Okay, that event is now called Orthodontist."


async def test_manage_with_no_events():
    res = await _skill(FakeProvider()).handle(Command("cancel it"), Intent("calendar_manage"))
    assert res.speech == "There are no events on my calendar to change."


async def test_manage_unknown_target_apologizes():
    provider = FakeProvider(_calcifer_events())
    llm = FakeLLM('{"action": "cancel", "target_index": 9}')
    res = await _skill(provider, llm=llm).handle(Command("cancel xyz"), Intent("calendar_manage"))
    assert not res.success
    assert provider.deleted == []


# -- event reminder -----------------------------------------------------------


async def test_event_reminder_stores_lead_offset():
    store = ReminderStore(":memory:")
    provider = FakeProvider([
        _event("p1", "Dentist", NOW + timedelta(hours=3), calendar_id=PERSONAL),
    ])
    llm = FakeLLM('{"target_index": 1, "lead_minutes": 30}')
    res = await _skill(provider, llm=llm, store=store).handle(
        Command("remind me 30 minutes before the dentist"), Intent("calendar_event_reminder")
    )
    assert provider.listed == [PERSONAL, CALCIFER]  # both calendars searched
    (pending,) = store.pending(NOW.timestamp())
    assert pending.due_at == (NOW + timedelta(hours=3)).timestamp() - 30 * 60
    assert pending.speech == "Reminder: Dentist starts in 30 minutes."
    assert res.speech == "Okay, I'll remind you 30 minutes before Dentist, in 2 hours."


async def test_event_reminder_too_soon_is_rejected():
    store = ReminderStore(":memory:")
    provider = FakeProvider([
        _event("p1", "Dentist", NOW + timedelta(minutes=10), calendar_id=PERSONAL),
    ])
    llm = FakeLLM('{"target_index": 1, "lead_minutes": 30}')
    res = await _skill(provider, llm=llm, store=store).handle(
        Command("remind me 30 minutes before the dentist"), Intent("calendar_event_reminder")
    )
    assert not res.success
    assert store.pending(NOW.timestamp()) == []


async def test_event_reminder_with_empty_calendar():
    res = await _skill(FakeProvider()).handle(
        Command("remind me before my next event"), Intent("calendar_event_reminder")
    )
    assert res.speech == "There's nothing coming up on your calendar to remind you about."


# -- watch toggle -------------------------------------------------------------


async def test_watch_toggle_via_slot():
    watcher = StubWatcher()
    skill = _skill(FakeProvider(), watcher=watcher)
    res = await skill.handle(Command("x"), Intent("calendar_watch", slots={"enabled": True}))
    assert watcher.enabled is True
    assert res.speech == "Okay, I'm watching your calendar."
    res = await skill.handle(Command("x"), Intent("calendar_watch", slots={"enabled": False}))
    assert watcher.enabled is False
    assert res.speech == "Okay, I'll stop announcing events."


async def test_watch_toggle_from_bare_text():
    watcher = StubWatcher()
    skill = _skill(FakeProvider(), watcher=watcher)
    await skill.handle(Command("stop watching my calendar"), Intent("calendar_watch"))
    assert watcher.enabled is False
    await skill.handle(Command("watch my calendar"), Intent("calendar_watch"))
    assert watcher.enabled is True


async def test_watch_toggle_works_when_provider_is_down():
    provider = FakeProvider()
    provider.raises = True
    watcher = StubWatcher()
    res = await _skill(provider, watcher=watcher).handle(
        Command("watch my calendar"), Intent("calendar_watch")
    )
    assert res.success
    assert watcher.enabled is True


# -- block toggle ---------------------------------------------------------------


async def test_block_by_voice_hides_future_queries():
    provider = FakeProvider([_event("p1", "Bedtime", NOW.replace(hour=22))])
    llm = FakeLLM('{"action": "block", "pattern": "bedtime"}')
    skill = _skill(provider, llm=llm)
    res = await skill.handle(Command("stop bringing up bedtime"), Intent("calendar_block"))
    assert res.speech == "Okay, I won't bring up bedtime anymore."
    res = await skill.handle(Command("calendar"), Intent("calendar_query", slots={"day": "today"}))
    assert res.speech == "Nothing on your calendar today."


async def test_block_without_pattern_apologizes():
    llm = FakeLLM('{"action": "block", "pattern": null}')
    res = await _skill(FakeProvider(), llm=llm).handle(
        Command("stop bringing that up"), Intent("calendar_block")
    )
    assert not res.success


async def test_unblock_restores_voice_blocked_pattern():
    blocklist = _blocklist()
    blocklist.block("bedtime", created_at=100.0)
    llm = FakeLLM('{"action": "unblock", "pattern": "bedtime"}')
    res = await _skill(FakeProvider(), llm=llm, blocklist=blocklist).handle(
        Command("you can mention bedtime again"), Intent("calendar_block")
    )
    assert res.speech == "Okay, I'll mention bedtime again."
    assert blocklist.patterns() == []


async def test_unblock_still_muted_by_config_says_so():
    blocklist = _blocklist(["bedtime"])
    blocklist.block("bedtime", created_at=100.0)
    llm = FakeLLM('{"action": "unblock", "pattern": "bedtime"}')
    res = await _skill(FakeProvider(), llm=llm, blocklist=blocklist).handle(
        Command("mention bedtime again"), Intent("calendar_block")
    )
    assert "still muted in my config file" in res.speech


async def test_unblock_config_only_pattern_cannot_be_removed_by_voice():
    llm = FakeLLM('{"action": "unblock", "pattern": "bedtime"}')
    res = await _skill(FakeProvider(), llm=llm, blocklist=_blocklist(["bedtime"])).handle(
        Command("mention bedtime again"), Intent("calendar_block")
    )
    assert res.speech == "bedtime is muted in my config file; I can't unmute it by voice."


async def test_unblock_unknown_pattern():
    llm = FakeLLM('{"action": "unblock", "pattern": "gym"}')
    res = await _skill(FakeProvider(), llm=llm).handle(
        Command("mention gym again"), Intent("calendar_block")
    )
    assert res.speech == "I wasn't ignoring anything called gym."


async def test_list_blocked_patterns():
    blocklist = _blocklist(["bedtime"])
    blocklist.block("gym", created_at=100.0)
    llm = FakeLLM('{"action": "list", "pattern": null}')
    res = await _skill(FakeProvider(), llm=llm, blocklist=blocklist).handle(
        Command("what are you ignoring"), Intent("calendar_block")
    )
    assert res.speech == "I'm not bringing up gym, and bedtime."


async def test_list_blocked_when_empty():
    llm = FakeLLM('{"action": "list", "pattern": null}')
    res = await _skill(FakeProvider(), llm=llm).handle(
        Command("what are you ignoring"), Intent("calendar_block")
    )
    assert res.speech == "I'm not ignoring any events."
