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


def test_survives_reopen(tmp_path):
    path = str(tmp_path / "reminders.db")
    store = ReminderStore(path)
    store.add(10.0, "persisted", created_at=0.0)
    store.close()

    reopened = ReminderStore(path)
    due = reopened.due(now=100.0)
    assert [r.speech for r in due] == ["persisted"]
    reopened.close()
