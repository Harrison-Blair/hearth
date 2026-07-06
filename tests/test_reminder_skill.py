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
        self.calls = []

    async def complete(self, prompt, *, system=None, json=False, label=""):
        self.calls.append(prompt)
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


def _managed_store():
    """Two pending reminders, soonest first: index 1 = timer, index 2 = call mom."""
    store = ReminderStore(":memory:")
    store.add(NOW.timestamp() + 300, "Reminder: call mom.", created_at=NOW.timestamp())
    store.add(NOW.timestamp() + 30, "Your timer is done.", created_at=NOW.timestamp())
    return store


def _manage(store, payload="{}"):
    llm = FakeLLM(payload)
    return ReminderSkill(store, llm, now=lambda: NOW), llm


async def test_manage_empty_store():
    store = ReminderStore(":memory:")
    skill, llm = _manage(store)
    res = await skill.handle(Command("cancel my reminders"), Intent("manage_reminders"))
    assert res.speech == "You don't have any reminders to cancel or change."
    assert llm.calls == []  # nothing to manage -> no LLM
    store.close()


async def test_bulk_cancel_confirms_before_deleting():
    store = _managed_store()
    skill, llm = _manage(store)
    res = await skill.handle(
        Command("cancel all my reminders"), Intent("manage_reminders")
    )
    assert res.expects_reply
    assert res.speech == "That will cancel all 2 reminders. Should I go ahead?"
    assert llm.calls == []  # bulk cancel never touches the LLM
    assert len(store.pending(NOW.timestamp())) == 2  # nothing deleted yet
    store.close()


async def test_bulk_cancel_reply_affirmative_deletes():
    store = _managed_store()
    skill, _ = _manage(store)
    await skill.handle(Command("cancel all my reminders"), Intent("manage_reminders"))
    res = await skill.handle_reply(Command("yes go ahead"))
    assert res.speech == "Okay, I've cancelled all 2 of your reminders."
    assert store.pending(NOW.timestamp()) == []
    store.close()


async def test_bulk_cancel_reply_negative_aborts():
    store = _managed_store()
    skill, _ = _manage(store)
    await skill.handle(Command("cancel all my reminders"), Intent("manage_reminders"))
    res = await skill.handle_reply(Command("no leave them"))
    assert res.speech == "Okay, I'll leave them."
    assert len(store.pending(NOW.timestamp())) == 2
    store.close()


async def test_bulk_cancel_reply_empty_aborts():
    store = _managed_store()
    skill, _ = _manage(store)
    await skill.handle(Command("cancel all my reminders"), Intent("manage_reminders"))
    res = await skill.handle_reply(Command(""))
    assert res.speech == "Okay, I'll leave them."
    assert len(store.pending(NOW.timestamp())) == 2
    store.close()


async def test_hyphenated_all_is_not_a_bulk_cancel():
    # "all-hands" must not match the bulk-cancel "all": this is a targeted cancel,
    # so it goes to the LLM and leaves the other reminders intact.
    store = _managed_store()
    skill, llm = _manage(store, json.dumps({"action": "cancel", "target_index": 1}))
    await skill.handle(
        Command("cancel the all-hands reminder"), Intent("manage_reminders")
    )
    assert llm.calls != []  # not bulk: the LLM resolved the target
    assert len(store.pending(NOW.timestamp())) == 1  # only one removed, not all
    store.close()


async def test_specific_cancel_by_index():
    store = _managed_store()
    skill, _ = _manage(store, json.dumps({"action": "cancel", "target_index": 2}))
    res = await skill.handle(
        Command("cancel my reminder to call mom"), Intent("manage_reminders")
    )
    assert res.speech == "Okay, I've cancelled your reminder to call mom."
    assert [r.speech for r in store.pending(NOW.timestamp())] == ["Your timer is done."]
    store.close()


async def test_cancel_timer_phrasing():
    store = _managed_store()
    skill, _ = _manage(store, json.dumps({"action": "cancel", "target_index": 1}))
    res = await skill.handle(Command("cancel the first one"), Intent("manage_reminders"))
    assert res.speech == "Okay, I've cancelled the timer."
    store.close()


async def test_reschedule_updates_due():
    store = _managed_store()
    skill, _ = _manage(
        store,
        json.dumps({"action": "reschedule", "target_index": 2, "new_at_time": "18:00"}),
    )
    res = await skill.handle(
        Command("change my call-mom reminder to 6 pm"), Intent("manage_reminders")
    )
    new_due = NOW.replace(hour=18, minute=0, second=0, microsecond=0).timestamp()
    assert res.speech == "Okay, I'll remind you to call mom in 3 hours instead."
    moved = next(r for r in store.pending(NOW.timestamp()) if r.speech == "Reminder: call mom.")
    assert moved.due_at == new_due
    store.close()


async def test_reschedule_without_time_fails():
    store = _managed_store()
    skill, _ = _manage(store, json.dumps({"action": "reschedule", "target_index": 2}))
    res = await skill.handle(Command("change my reminder"), Intent("manage_reminders"))
    assert not res.success
    assert res.speech == "Sorry, I didn't catch the new time."
    store.close()


async def test_rename_updates_speech():
    store = _managed_store()
    skill, _ = _manage(
        store,
        json.dumps({"action": "rename", "target_index": 2, "new_message": "buy milk"}),
    )
    res = await skill.handle(
        Command("change it to say buy milk"), Intent("manage_reminders")
    )
    assert res.speech == "Okay, that reminder now says buy milk."
    assert any(
        r.speech == "Reminder: buy milk." for r in store.pending(NOW.timestamp())
    )
    store.close()


async def test_unresolved_target_message():
    store = _managed_store()
    skill, _ = _manage(store, json.dumps({"action": "cancel", "target_index": None}))
    res = await skill.handle(
        Command("cancel the thing"), Intent("manage_reminders")
    )
    assert not res.success
    assert res.speech == "I couldn't tell which reminder you meant."
    assert len(store.pending(NOW.timestamp())) == 2  # nothing removed
    store.close()
