from assistant.storage.calendar_state import CalendarStateStore


def test_mark_and_was_announced(tmp_path):
    store = CalendarStateStore(str(tmp_path / "state.db"))
    assert not store.was_announced("ev1", 1000.0)
    store.mark("ev1", 1000.0, announced_at=900.0)
    assert store.was_announced("ev1", 1000.0)
    store.close()


def test_same_event_different_start_is_distinct(tmp_path):
    store = CalendarStateStore(str(tmp_path / "state.db"))
    store.mark("ev1", 1000.0, announced_at=900.0)
    # A rescheduled event (new start epoch) must be announced again.
    assert not store.was_announced("ev1", 2000.0)
    store.close()


def test_purge_before_drops_only_old_rows(tmp_path):
    store = CalendarStateStore(str(tmp_path / "state.db"))
    store.mark("old", 100.0, announced_at=90.0)
    store.mark("new", 5000.0, announced_at=4900.0)
    assert store.purge_before(1000.0) == 1
    assert not store.was_announced("old", 100.0)
    assert store.was_announced("new", 5000.0)
    store.close()


def test_dedupe_survives_reopen(tmp_path):
    db = str(tmp_path / "state.db")
    first = CalendarStateStore(db)
    first.mark("ev1", 1000.0, announced_at=900.0)
    first.close()

    second = CalendarStateStore(db)  # simulates a daemon restart
    assert second.was_announced("ev1", 1000.0)
    second.close()


def test_blocked_patterns_add_remove_list(tmp_path):
    store = CalendarStateStore(str(tmp_path / "state.db"))
    assert store.blocked_patterns() == []
    store.add_blocked("bedtime", created_at=100.0)
    store.add_blocked("wake up", created_at=200.0)
    assert store.blocked_patterns() == ["bedtime", "wake up"]
    assert store.remove_blocked("bedtime") == 1
    assert store.remove_blocked("bedtime") == 0
    assert store.blocked_patterns() == ["wake up"]
    store.close()


def test_blocked_patterns_survive_reopen(tmp_path):
    db = str(tmp_path / "state.db")
    first = CalendarStateStore(db)
    first.add_blocked("bedtime", created_at=100.0)
    first.close()

    second = CalendarStateStore(db)  # simulates a daemon restart
    assert second.blocked_patterns() == ["bedtime"]
    second.close()


def test_blocked_add_twice_is_idempotent(tmp_path):
    store = CalendarStateStore(str(tmp_path / "state.db"))
    store.add_blocked("bedtime", created_at=100.0)
    store.add_blocked("bedtime", created_at=200.0)  # no primary-key blowup
    assert store.blocked_patterns() == ["bedtime"]
    store.close()


def test_mark_twice_is_idempotent(tmp_path):
    store = CalendarStateStore(str(tmp_path / "state.db"))
    store.mark("ev1", 1000.0, announced_at=900.0)
    store.mark("ev1", 1000.0, announced_at=950.0)  # no primary-key blowup
    assert store.was_announced("ev1", 1000.0)
    store.close()
