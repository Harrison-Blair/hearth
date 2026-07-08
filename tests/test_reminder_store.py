import sqlite3

from assistant.storage.reminders import ReminderStore


def test_due_filters_future_and_orders_by_due_at():
    store = ReminderStore(":memory:")
    second = store.add(100.0, "second", created_at=0.0)
    first = store.add(50.0, "first", created_at=0.0)
    store.add(200.0, "future", created_at=0.0)

    due = store.due(now=150.0)

    assert [(r.id, r.speech) for r in due] == [(first, "first"), (second, "second")]


def test_pending_lists_future_ordered():
    store = ReminderStore(":memory:")
    store.add(200.0, "later", created_at=0.0)
    store.add(150.0, "sooner", created_at=0.0)
    store.add(50.0, "past", created_at=0.0)  # already due -> excluded

    pending = store.pending(now=100.0)
    assert [r.speech for r in pending] == ["sooner", "later"]


def test_delete_removes_single_reminder():
    store = ReminderStore(":memory:")
    store.add(100.0, "keep", created_at=0.0)
    drop = store.add(200.0, "drop", created_at=0.0)
    store.delete(drop)
    assert [r.speech for r in store.pending(now=0.0)] == ["keep"]


def test_delete_pending_returns_count_and_leaves_past():
    store = ReminderStore(":memory:")
    store.add(200.0, "future-a", created_at=0.0)
    store.add(300.0, "future-b", created_at=0.0)
    store.add(50.0, "past", created_at=0.0)  # not pending -> kept

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


_LEGACY_SCHEMA = """
CREATE TABLE reminders (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    due_at     REAL    NOT NULL,
    speech     TEXT    NOT NULL,
    created_at REAL    NOT NULL
);
CREATE INDEX ix_reminders_due ON reminders (due_at);
"""


def _make_legacy_db(path):
    conn = sqlite3.connect(path)
    conn.executescript(_LEGACY_SCHEMA)
    conn.execute(
        "INSERT INTO reminders (due_at, speech, created_at) VALUES (100, 'Your timer is done.', 0)"
    )
    conn.execute(
        "INSERT INTO reminders (due_at, speech, created_at) VALUES (200, 'Reminder: call mom.', 0)"
    )
    conn.commit()
    conn.close()


def test_migrates_legacy_schema_and_backfills_timer_kind(tmp_path):
    path = str(tmp_path / "reminders.db")
    _make_legacy_db(path)

    store = ReminderStore(path)
    pending = store.pending(now=0.0)

    assert {r.speech: r.kind for r in pending} == {
        "Your timer is done.": "timer",
        "Reminder: call mom.": "reminder",
    }
    assert all(r.label is None for r in pending)
    store.close()


def test_backfill_runs_only_when_column_is_added(tmp_path):
    path = str(tmp_path / "reminders.db")
    _make_legacy_db(path)
    store = ReminderStore(path)  # migrates + backfills
    # A post-migration *reminder* whose speech matches the timer sentence must
    # not be reclassified by a later open.
    store.add(300.0, "Your timer is done.", created_at=0.0, kind="reminder")
    store.close()

    reopened = ReminderStore(path)
    kinds = [r.kind for r in reopened.pending(now=0.0) if r.due_at == 300.0]
    assert kinds == ["reminder"]
    reopened.close()


def test_add_stores_kind_and_label():
    store = ReminderStore(":memory:")
    store.add(200.0, "Your pasta timer is done.", created_at=0.0, kind="timer", label="pasta")

    (timer,) = store.pending(now=0.0)
    assert timer.kind == "timer"
    assert timer.label == "pasta"
    (due,) = store.due(now=300.0)
    assert (due.kind, due.label) == ("timer", "pasta")


def test_add_stores_and_reads_back_interval():
    store = ReminderStore(":memory:")
    store.add(900.0, "Reminder: stretch.", created_at=0.0, interval=900.0)
    store.add(200.0, "Reminder: call mom.", created_at=0.0)  # one-shot -> None

    by_speech = {r.speech: r.interval for r in store.pending(now=0.0)}
    assert by_speech == {"Reminder: stretch.": 900.0, "Reminder: call mom.": None}


def test_legacy_db_migrates_interval_column_as_null(tmp_path):
    path = str(tmp_path / "reminders.db")
    _make_legacy_db(path)  # schema predates the interval column
    store = ReminderStore(path)
    assert all(r.interval is None for r in store.pending(now=0.0))
    store.close()


def test_pending_and_delete_pending_filter_by_kind():
    store = ReminderStore(":memory:")
    store.add(200.0, "Your timer is done.", created_at=0.0, kind="timer", label="pasta")
    store.add(300.0, "Reminder: call mom.", created_at=0.0)

    assert [r.label for r in store.pending(now=0.0, kind="timer")] == ["pasta"]
    assert [r.speech for r in store.pending(now=0.0, kind="reminder")] == ["Reminder: call mom."]
    assert len(store.pending(now=0.0)) == 2

    assert store.delete_pending(now=0.0, kind="timer") == 1
    assert [r.kind for r in store.pending(now=0.0)] == ["reminder"]
