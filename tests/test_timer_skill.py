from datetime import datetime

from assistant.core.events import Command, Intent
from assistant.skills.timer import TimerSkill
from assistant.storage.reminders import ReminderStore

NOW = datetime(2026, 6, 25, 15, 0, 0).astimezone()


def _skill(store):
    return TimerSkill(store, now=lambda: NOW)


async def test_timer_sets_and_confirms():
    store = ReminderStore(":memory:")
    res = await _skill(store).handle(Command("set a timer for 5 minutes"), Intent("timer"))

    assert res.success
    assert res.speech == "Okay, timer set for 5 minutes."
    (timer,) = store.pending(NOW.timestamp())
    assert timer.kind == "timer"
    assert timer.label is None
    assert timer.speech == "Your timer is done."
    assert timer.due_at == NOW.timestamp() + 300
    store.close()


async def test_timer_uses_duration_slot_when_text_lacks_it():
    store = ReminderStore(":memory:")
    res = await _skill(store).handle(
        Command("set a five-minute timer going"),
        Intent(type="timer", slots={"duration": "5 minutes"}),
    )

    assert res.success
    (timer,) = store.pending(NOW.timestamp())
    assert timer.due_at == NOW.timestamp() + 300
    store.close()


async def test_named_timer_stores_label_and_firing_speech():
    store = ReminderStore(":memory:")
    res = await _skill(store).handle(
        Command("set a pasta timer for 10 minutes"),
        Intent(type="timer", slots={"duration": "10 minutes", "name": "pasta"}),
    )

    assert res.speech == "Okay, pasta timer set for 10 minutes."
    (timer,) = store.pending(NOW.timestamp())
    assert timer.label == "pasta"
    assert timer.speech == "Your pasta timer is done."
    store.close()


async def test_timer_failure_when_no_duration():
    store = ReminderStore(":memory:")
    res = await _skill(store).handle(Command("set a timer"), Intent("timer"))

    assert not res.success
    assert store.pending(NOW.timestamp()) == []
    store.close()


async def test_list_when_empty():
    store = ReminderStore(":memory:")
    res = await _skill(store).handle(Command("what timers do I have"), Intent("list_timers"))

    assert res.speech == "You don't have any timers running."
    store.close()


async def test_list_excludes_reminders():
    store = ReminderStore(":memory:")
    store.add(NOW.timestamp() + 300, "Reminder: call mom.", created_at=NOW.timestamp())
    store.add(
        NOW.timestamp() + 600, "Your timer is done.", created_at=NOW.timestamp(), kind="timer"
    )
    res = await _skill(store).handle(Command("list my timers"), Intent("list_timers"))

    assert res.speech == "You have 1 timer: a timer in 10 minutes."
    store.close()


async def test_list_many_names_named_timers_soonest_first():
    store = ReminderStore(":memory:")
    store.add(
        NOW.timestamp() + 600, "Your timer is done.", created_at=NOW.timestamp(), kind="timer"
    )
    store.add(
        NOW.timestamp() + 180, "Your pasta timer is done.",
        created_at=NOW.timestamp(), kind="timer", label="pasta",
    )
    res = await _skill(store).handle(Command("list my timers"), Intent("list_timers"))

    assert res.speech == (
        "You have 2 timers: the pasta timer in 3 minutes, and a timer in 10 minutes."
    )
    store.close()


def _two_timers():
    store = ReminderStore(":memory:")
    store.add(
        NOW.timestamp() + 180, "Your pasta timer is done.",
        created_at=NOW.timestamp(), kind="timer", label="pasta",
    )
    store.add(
        NOW.timestamp() + 600, "Your timer is done.", created_at=NOW.timestamp(), kind="timer"
    )
    return store


async def test_cancel_by_name():
    store = _two_timers()
    res = await _skill(store).handle(
        Command("cancel the pasta timer"), Intent(type="cancel_timer", slots={"name": "pasta"})
    )

    assert res.speech == "Okay, I've cancelled the pasta timer."
    assert [t.label for t in store.pending(NOW.timestamp(), kind="timer")] == [None]
    store.close()


async def test_cancel_by_unknown_name_fails():
    store = _two_timers()
    res = await _skill(store).handle(
        Command("cancel the egg timer"), Intent(type="cancel_timer", slots={"name": "egg"})
    )

    assert not res.success
    assert len(store.pending(NOW.timestamp(), kind="timer")) == 2
    store.close()


async def test_cancel_lone_timer_without_name():
    store = ReminderStore(":memory:")
    store.add(
        NOW.timestamp() + 600, "Your timer is done.", created_at=NOW.timestamp(), kind="timer"
    )
    res = await _skill(store).handle(Command("cancel the timer"), Intent("cancel_timer"))

    assert res.speech == "Okay, I've cancelled the timer."
    assert store.pending(NOW.timestamp(), kind="timer") == []
    store.close()


async def test_ambiguous_cancel_asks_which():
    store = _two_timers()
    res = await _skill(store).handle(Command("cancel my timer"), Intent("cancel_timer"))

    assert not res.success
    assert "which" in res.speech.lower()
    assert "pasta" in res.speech
    assert len(store.pending(NOW.timestamp(), kind="timer")) == 2
    store.close()


async def test_cancel_with_none_running():
    store = ReminderStore(":memory:")
    store.add(NOW.timestamp() + 300, "Reminder: call mom.", created_at=NOW.timestamp())
    res = await _skill(store).handle(Command("cancel the timer"), Intent("cancel_timer"))

    assert res.speech == "You don't have any timers running."
    assert len(store.pending(NOW.timestamp())) == 1  # the reminder is untouched
    store.close()
