"""EventReader is a read-only, cursor-based seam over EventLog; NoOpConsumer
proves the Layer-2 consumer protocol without coupling to the write path."""
from __future__ import annotations

from hearth.memory.consumer import NoOpConsumer, pull_once
from hearth.memory.log import EventLog
from hearth.memory.reader import EventReader


def test_read_since_cursor_ordered(tmp_path):
    log = EventLog(str(tmp_path / "events.db"))
    reader = EventReader(log)

    events = [
        log.append("s1", "t1", "user_input", "user", {"i": i}) for i in range(5)
    ]
    ids = [e.id for e in events]

    assert reader.latest_cursor() == ids[-1]

    since_second = reader.read_since(ids[1], limit=100)
    assert [e.id for e in since_second] == ids[2:]
    assert [e.id for e in since_second] == sorted(e.id for e in since_second)

    assert reader.read_since(0, limit=2) == events[:2]

    empty_log = EventLog(str(tmp_path / "empty.db"))
    assert EventReader(empty_log).latest_cursor() == 0


async def test_noop_consumer_pulls_events(tmp_path):
    log = EventLog(str(tmp_path / "events.db"))
    reader = EventReader(log)

    log.append("s1", "t1", "user_input", "user", {"i": 0})
    log.append("s1", "t1", "final_answer", "brain", {"i": 1})

    received: list = []

    class SpyConsumer:
        async def consume(self, events):
            received.extend(events)

    cursor = await pull_once(reader, SpyConsumer(), cursor=0)

    assert [e.payload["i"] for e in received] == [0, 1]
    assert cursor == reader.latest_cursor()

    # NoOpConsumer implements the same seam and does nothing observable.
    noop_cursor = await pull_once(reader, NoOpConsumer(), cursor=0)
    assert noop_cursor == reader.latest_cursor()


async def test_write_path_unaffected_without_consumer(tmp_path):
    log = EventLog(str(tmp_path / "events.db"))

    # No reader, no consumer ever constructed or run.
    e1 = log.append("s1", "t1", "user_input", "user", {"text": "hi"})
    e2 = log.append("s1", "t1", "final_answer", "brain", {"text": "hello"})

    assert log.read_session("s1") == [e1, e2]

    # append() exposes no reader/consumer coupling.
    assert not hasattr(log, "consumer")
    assert not hasattr(log, "reader")
    assert not hasattr(log, "attach_consumer")
