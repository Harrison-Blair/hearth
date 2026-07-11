"""EventLog is append-only, orders by id, and scopes reads by session."""
from __future__ import annotations

from hearth.memory.log import EventLog


def test_event_log_append_and_read(tmp_path):
    log = EventLog(str(tmp_path / "events.db"))

    e1 = log.append("s1", "t1", "user_input", "user", {"text": "hi"})
    e2 = log.append("s1", "t1", "final_answer", "brain", {"text": "hello"})
    log.append("s2", "t2", "user_input", "user", {"text": "other session"})

    events = log.read_session("s1")

    assert [e.id for e in events] == [e1.id, e2.id]
    assert events[0].type == "user_input"
    assert events[0].payload == {"text": "hi"}
    assert events[1].type == "final_answer"
    assert events[1].payload == {"text": "hello"}

    # append-only: no mutation API is exposed.
    assert not hasattr(log, "update")
    assert not hasattr(log, "delete")
