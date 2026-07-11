"""Veneer error-surfacing and WebSocket-robustness contract.

Covers `curate_error` (protocol-level policy: what reaches the client for a
`BrainError` vs. any other exception) and `Veneer._handle_connection`'s
handling of both curated errors and a mid-turn `websockets.ConnectionClosed`.
Uses the same in-memory fake `Loop`/websocket doubles as `test_veneer.py` --
no real sockets for the unit-level cases.
"""
from __future__ import annotations

import logging

import websockets

from hearth.brain.errors import BrainError
from hearth.memory.log import EventLog
from hearth.veneer.protocol import curate_error
from hearth.veneer.server import Veneer


class _FakeLoop:
    """Same shape as test_veneer.py's fake: scripted answer or raised error."""

    def __init__(self, log, answer="hi there", raise_exc=None):
        self._log = log
        self._answer = answer
        self._raise_exc = raise_exc

    async def run_turn(self, session_id, turn_id, transcript, emit=None):
        self._log.append(session_id, turn_id, "user_input", "user", {"text": transcript})
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
    veneer = Veneer(loop, log, config=None)

    raw = json.dumps({"turn_id": "t1", "final_user_transcript": "hi"})
    ws = _FakeWebSocket([raw])

    await veneer._handle_connection(ws)

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
    veneer = Veneer(loop, log, config=None)

    raw = json.dumps({"turn_id": "t1", "final_user_transcript": "hi"})
    ws = _FakeWebSocket([raw])

    await veneer._handle_connection(ws)

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
    veneer = Veneer(loop, _EventLogStub(), config=None)

    raw = json.dumps({"turn_id": "t1", "final_user_transcript": "hi"})
    ws = _FakeWebSocket([raw], close_on_send=True)

    with caplog.at_level(logging.INFO):
        await veneer._handle_connection(ws)  # must not raise

    assert not any(record.levelno >= logging.ERROR for record in caplog.records)
    assert any("ConnectionClosed" in record.message or "disconnect" in record.message.lower()
               for record in caplog.records)
