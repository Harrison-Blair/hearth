from assistant.storage.reminders import ReminderStore


def test_due_filters_future_and_orders_by_due_at():
    store = ReminderStore(":memory:")
    second = store.add(100.0, "second", created_at=0.0)
    first = store.add(50.0, "first", created_at=0.0)
    store.add(200.0, "future", created_at=0.0)

    due = store.due(now=150.0)

    assert [(r.id, r.speech) for r in due] == [(first, "first"), (second, "second")]


def test_pending_lists_future_unfired_ordered():
    store = ReminderStore(":memory:")
    store.add(200.0, "later", created_at=0.0)
    store.add(150.0, "sooner", created_at=0.0)
    store.add(50.0, "past", created_at=0.0)  # already due -> excluded
    fired = store.add(300.0, "fired", created_at=0.0)
    store.mark_fired(fired)  # fired -> excluded

    pending = store.pending(now=100.0)
    assert [r.speech for r in pending] == ["sooner", "later"]


def test_mark_fired_excludes_from_due():
    store = ReminderStore(":memory:")
    rid = store.add(10.0, "x", created_at=0.0)
    store.mark_fired(rid)
    assert store.due(now=100.0) == []


def test_delete_removes_single_reminder():
    store = ReminderStore(":memory:")
    store.add(100.0, "keep", created_at=0.0)
    drop = store.add(200.0, "drop", created_at=0.0)
    store.delete(drop)
    assert [r.speech for r in store.pending(now=0.0)] == ["keep"]


def test_delete_pending_returns_count_and_leaves_past_and_fired():
    store = ReminderStore(":memory:")
    store.add(200.0, "future-a", created_at=0.0)
    store.add(300.0, "future-b", created_at=0.0)
    store.add(50.0, "past", created_at=0.0)  # not pending -> kept
    fired = store.add(400.0, "fired", created_at=0.0)
    store.mark_fired(fired)  # not pending -> kept

    removed = store.delete_pending(now=100.0)
    assert removed == 2
    assert store.pending(now=100.0) == []
    assert [r.speech for r in store.due(now=100.0)] == ["past"]


def test_update_due_and_speech_reflected_in_pending():
    store = ReminderStore(":memory:")
    rid = store.add(200.0, "Reminder: call mom.", created_at=0.0)
    store.update_due(rid, 500.0)
    store.update_speech(rid, "Reminder: buy milk.")
    pending = store.pending(now=100.0)
    assert [(r.due_at, r.speech) for r in pending] == [(500.0, "Reminder: buy milk.")]


def test_survives_reopen(tmp_path):
    path = str(tmp_path / "reminders.db")
    store = ReminderStore(path)
    store.add(10.0, "persisted", created_at=0.0)
    store.close()

    reopened = ReminderStore(path)
    due = reopened.due(now=100.0)
    assert [r.speech for r in due] == ["persisted"]
    reopened.close()
