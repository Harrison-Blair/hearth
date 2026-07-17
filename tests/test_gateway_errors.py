"""Gateway error-surfacing and WebSocket-robustness contract.

Covers `curate_error` (protocol-level policy: what reaches the client for a
`BrainError` vs. any other exception) and `Gateway._handle_connection`'s
handling of both curated errors and a mid-turn `websockets.ConnectionClosed`.
Uses the same in-memory fake `Loop`/websocket doubles as `test_gateway.py` --
no real sockets for the unit-level cases.
"""
from __future__ import annotations

import logging

import websockets

from hearth.brain.errors import BrainError
from hearth.memory.log import EventLog
from hearth.gateway.protocol import curate_error
from hearth.gateway.server import Gateway


class _FakeLoop:
    """Same shape as test_gateway.py's fake: scripted answer or raised error."""

    def __init__(self, log, answer="hi there", raise_exc=None):
        self._log = log
        self._answer = answer
        self._raise_exc = raise_exc

    async def run_turn(self, session_id, turn_id, transcript, surface, emit=None):
        self._log.append(session_id, turn_id, "user_input", surface, {"text": transcript})
        if self._raise_exc is not None:
            raise self._raise_exc
        self._log.append(session_id, turn_id, "final_answer", "brain", {"text": self._answer})
        return self._answer


class _FakeWebSocket:
    """An async-iterable of raw inbound messages that records sent frames.

    If `close_on_send` is set, `send` raises `websockets.ConnectionClosed`
    instead of recording, simulating a client disconnect mid-turn.
    """

    def __init__(self, raw_messages, close_on_send=False):
        self._raw_messages = iter(raw_messages)
        self._close_on_send = close_on_send
        self.sent = []

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self._raw_messages)
        except StopIteration:
            raise StopAsyncIteration

    async def send(self, data):
        if self._close_on_send:
            raise websockets.ConnectionClosed(None, None)
        self.sent.append(data)


def _event_types(log):
    rows = log._conn.execute("SELECT type FROM events ORDER BY id").fetchall()
    return [row[0] for row in rows]


def test_curate_error_brain_error_returns_reason():
    exc = BrainError("backend unreachable", detail="connection refused to 10.0.0.1:11434")
    assert curate_error(exc) == "backend unreachable"


def test_curate_error_generic_exception_returns_generic_message():
    exc = ValueError("boom")
    assert curate_error(exc) == "the turn failed"


async def test_brain_error_reaches_client_as_curated_reason(tmp_path):
    import json

    log = EventLog(str(tmp_path / "events.db"))
    exc = BrainError("backend unreachable", detail="leaked internal detail")
    loop = _FakeLoop(log, raise_exc=exc)
    gateway = Gateway(loop, log, config=None)

    raw = json.dumps({"turn_id": "t1", "final_user_transcript": "hi", "surface": "chat"})
    ws = _FakeWebSocket([raw])

    await gateway._handle_connection(ws)

    assert len(ws.sent) == 1
    message = json.loads(ws.sent[0])
    assert message["type"] == "error"
    assert message["message"] == "backend unreachable"

    error_rows = log._conn.execute(
        "SELECT payload_json FROM events WHERE type = 'error'"
    ).fetchall()
    assert len(error_rows) == 1
    assert "leaked internal detail" in error_rows[0][0]


async def test_generic_exception_reaches_client_as_generic_message(tmp_path):
    import json

    log = EventLog(str(tmp_path / "events.db"))
    exc = RuntimeError("boom: leaked internal detail")
    loop = _FakeLoop(log, raise_exc=exc)
    gateway = Gateway(loop, log, config=None)

    raw = json.dumps({"turn_id": "t1", "final_user_transcript": "hi", "surface": "chat"})
    ws = _FakeWebSocket([raw])

    await gateway._handle_connection(ws)

    assert len(ws.sent) == 1
    message = json.loads(ws.sent[0])
    assert message["type"] == "error"
    assert message["message"] == "the turn failed"

    error_rows = log._conn.execute(
        "SELECT payload_json FROM events WHERE type = 'error'"
    ).fetchall()
    assert len(error_rows) == 1
    assert "boom: leaked internal detail" in error_rows[0][0]


async def test_connection_closed_mid_turn_handled_cleanly(caplog):
    import json

    class _EventLogStub:
        def append(self, *args, **kwargs):
            pass

    loop = _FakeLoop(_EventLogStub())
    gateway = Gateway(loop, _EventLogStub(), config=None)

    raw = json.dumps({"turn_id": "t1", "final_user_transcript": "hi", "surface": "chat"})
    ws = _FakeWebSocket([raw], close_on_send=True)

    with caplog.at_level(logging.INFO):
        await gateway._handle_connection(ws)  # must not raise

    assert not any(record.levelno >= logging.ERROR for record in caplog.records)
    assert any("ConnectionClosed" in record.message or "disconnect" in record.message.lower()
               for record in caplog.records)


async def test_connection_accepted_is_logged(caplog):
    """A new INFO log line, tagged category="connection", is emitted as soon
    as a connection is accepted -- before the first turn is processed."""
    import json

    class _EventLogStub:
        def append(self, *args, **kwargs):
            pass

    class _OrderCheckingLoop:
        async def run_turn(self, session_id, turn_id, transcript, surface, emit=None):
            logging.getLogger("test.turn").info("turn started")
            return "ok"

    gateway = Gateway(_OrderCheckingLoop(), _EventLogStub(), config=None)

    raw = json.dumps({"turn_id": "t1", "final_user_transcript": "hi", "surface": "chat"})
    ws = _FakeWebSocket([raw])

    with caplog.at_level(logging.INFO):
        await gateway._handle_connection(ws)

    messages = [record.getMessage() for record in caplog.records]
    connect_idx = next((i for i, m in enumerate(messages) if "connected" in m.lower()), None)
    turn_idx = next((i for i, m in enumerate(messages) if m == "turn started"), None)
    assert connect_idx is not None, f"no 'connected' log record found in {messages!r}"
    assert turn_idx is not None, f"no 'turn started' log record found in {messages!r}"
    assert connect_idx < turn_idx

    connect_record = caplog.records[connect_idx]
    assert connect_record.levelno == logging.INFO
    assert connect_record.category == "connection"


async def test_disconnect_and_malformed_frame_carry_category_tag(caplog):
    """The existing disconnect-mid-turn and malformed-frame log lines both
    carry category="connection" on their LogRecord."""
    import json

    class _EventLogStub:
        def append(self, *args, **kwargs):
            pass

    loop = _FakeLoop(_EventLogStub())
    gateway = Gateway(loop, _EventLogStub(), config=None)

    raw = json.dumps({"turn_id": "t1", "final_user_transcript": "hi", "surface": "chat"})
    ws = _FakeWebSocket([raw], close_on_send=True)

    with caplog.at_level(logging.INFO):
        await gateway._handle_connection(ws)

    disconnect_records = [r for r in caplog.records if "disconnect" in r.getMessage().lower()]
    assert disconnect_records
    assert all(getattr(r, "category", None) == "connection" for r in disconnect_records)

    caplog.clear()
    ws2 = _FakeWebSocket(["{not json"])

    with caplog.at_level(logging.WARNING):
        await gateway._handle_connection(ws2)

    malformed_records = [r for r in caplog.records if "malformed" in r.getMessage().lower()]
    assert malformed_records
    assert all(getattr(r, "category", None) == "connection" for r in malformed_records)


async def test_frame_without_surface_is_rejected_as_malformed(tmp_path):
    """AC-6: a frame omitting `surface` takes the EXISTING malformed-frame path
    -- a curated `malformed request` error, its content never echoed, and the
    connection stays alive to serve a well-formed follow-up. No second
    rejection path, no wire-level default."""
    import json

    log = EventLog(str(tmp_path / "events.db"))
    loop = _FakeLoop(log, answer="still alive")
    gateway = Gateway(loop, log, config=None)

    no_surface = json.dumps({"turn_id": "t1", "final_user_transcript": "secret content"})
    well_formed = json.dumps(
        {"turn_id": "t2", "final_user_transcript": "hello again", "surface": "chat"}
    )
    ws = _FakeWebSocket([no_surface, well_formed])

    await gateway._handle_connection(ws)

    replies = [json.loads(frame) for frame in ws.sent]

    # First reply: the existing curated malformed-request error, no content echoed.
    assert replies[0] == {"type": "error", "turn_id": "", "message": "malformed request"}
    assert "secret content" not in ws.sent[0]

    # Connection stayed alive: the well-formed follow-up was served normally.
    assert [r["type"] for r in replies[1:]] == ["answer", "done"]
    assert replies[1]["text"] == "still alive"

    # Exactly one error event logged (the malformed frame), tagged as the
    # existing veneer/malformed provenance -- no new rejection path.
    error_rows = log._conn.execute(
        "SELECT provenance, payload_json FROM events WHERE type = 'error'"
    ).fetchall()
    assert len(error_rows) == 1
    assert error_rows[0][0] == "veneer"
    assert "secret content" not in error_rows[0][1]
