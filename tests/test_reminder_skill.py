import json
from datetime import datetime

from assistant.core.events import Command, Intent
from assistant.skills.reminder import ReminderSkill
from assistant.storage.reminders import ReminderStore

NOW = datetime(2026, 6, 25, 15, 0, 0).astimezone()


class FakeStore:
    def __init__(self):
        self.added = []

    def add(self, due_at, speech, *, created_at):
        self.added.append((due_at, speech, created_at))
        return len(self.added)


class FakeLLM:
    def __init__(self, payload="{}"):
        self.payload = payload

    async def complete(self, prompt, *, system=None, json=False):
        return self.payload

    async def health(self):
        return True


def _skill(store, llm=None):
    return ReminderSkill(store, llm or FakeLLM(), now=lambda: NOW)


async def test_timer_sets_and_confirms():
    store = FakeStore()
    res = await _skill(store).handle(Command("set a timer for 5 minutes"), Intent("timer"))
    assert res.success
    assert res.speech == "Okay, timer set for 5 minutes."
    due, speech, _ = store.added[0]
    assert speech == "Your timer is done."
    assert due == NOW.timestamp() + 300


async def test_timer_failure_when_no_duration():
    store = FakeStore()
    res = await _skill(store).handle(Command("set a timer"), Intent("timer"))
    assert not res.success
    assert store.added == []


async def test_relative_reminder():
    store = FakeStore()
    res = await _skill(store).handle(
        Command("remind me in 30 seconds to stretch"), Intent("reminder")
    )
    assert res.speech == "Okay, I'll remind you to stretch in 30 seconds."
    due, speech, _ = store.added[0]
    assert speech == "Reminder: stretch."
    assert due == NOW.timestamp() + 30


async def test_reminder_failure_when_no_time():
    store = FakeStore()
    llm = FakeLLM(json.dumps({"delay_seconds": None, "at_time": None, "message": "x"}))
    res = await _skill(store, llm).handle(
        Command("remind me to do a thing"), Intent("reminder")
    )
    assert not res.success
    assert store.added == []


def _list_skill(store):
    return ReminderSkill(store, FakeLLM(), now=lambda: NOW)


async def test_list_when_empty():
    res = await _list_skill(ReminderStore(":memory:")).handle(
        Command("what are my reminders"), Intent("list_reminders")
    )
    assert res.speech == "You don't have any reminders set."


async def test_list_single_reminder():
    store = ReminderStore(":memory:")
    store.add(NOW.timestamp() + 600, "Reminder: stretch.", created_at=NOW.timestamp())
    res = await _list_skill(store).handle(
        Command("my reminders"), Intent("list_reminders")
    )
    assert res.speech == "You have 1 reminder: stretch in 10 minutes."
    store.close()


async def test_list_reminder_and_timer_ordered():
    store = ReminderStore(":memory:")
    store.add(NOW.timestamp() + 300, "Reminder: call mom.", created_at=NOW.timestamp())
    store.add(NOW.timestamp() + 30, "Your timer is done.", created_at=NOW.timestamp())
    res = await _list_skill(store).handle(
        Command("do I have any reminders"), Intent("list_reminders")
    )
    assert res.speech == (
        "You have 2 reminders: a timer in 30 seconds, and call mom in 5 minutes."
    )
    store.close()
