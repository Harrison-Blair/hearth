"""Veneer WebSocket contract: server drives Loop.run_turn over the wire.

Uses an in-process `Veneer` (loopback on 127.0.0.1, ephemeral port) with a
fake `Loop` so these tests don't depend on FTHR-002's real backend wiring.
"""
from __future__ import annotations

import websockets

from hearth.events import ToolActivity
from hearth.memory.log import EventLog
from hearth.veneer.client import send_turn
from hearth.veneer.server import Veneer


class _FakeLoop:
    """Stands in for `hearth.loop.Loop`: same `run_turn` signature, scripted
    behavior (canned answer, canned tool activity, or a raised error)."""

    def __init__(self, log, answer="hi there", activities=None, raise_exc=None):
        self._log = log
        self._answer = answer
        self._activities = activities or []
        self._raise_exc = raise_exc

    async def run_turn(self, session_id, turn_id, transcript, emit=None):
        self._log.append(session_id, turn_id, "user_input", "user", {"text": transcript})
        if self._raise_exc is not None:
            raise self._raise_exc
        for phase, label in self._activities:
            await emit(ToolActivity(turn_id=turn_id, phase=phase, label=label))
        self._log.append(session_id, turn_id, "final_answer", "brain", {"text": self._answer})
        return self._answer


async def _serve(veneer):
    """Start a loopback server for `veneer` on an ephemeral port; return the
    running `websockets` server (async context manager) and its port."""
    server = await websockets.serve(veneer._handle_connection, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    return server, port


def _event_types(log):
    rows = log._conn.execute("SELECT type FROM events ORDER BY id").fetchall()
    return [row[0] for row in rows]


async def test_veneer_roundtrip(tmp_path):
    log = EventLog(str(tmp_path / "events.db"))
    loop = _FakeLoop(log, answer="answer text")
    veneer = Veneer(loop, log, config=None)
    server, port = await _serve(veneer)

    try:
        async with websockets.connect(f"ws://127.0.0.1:{port}") as ws:
            messages = await send_turn(ws, "hello")
    finally:
        server.close()
        await server.wait_closed()

    assert len(messages) == 2
    turn_id = messages[0]["turn_id"]
    assert messages[0] == {"type": "answer", "turn_id": turn_id, "text": "answer text"}
    assert messages[1] == {"type": "done", "turn_id": turn_id}

    assert _event_types(log) == ["user_input", "final_answer"]


def test_no_engine_side_component_named_veneer():
    """AC-2: no engine-side component is named "veneer". The server and
    protocol modules moved to `hearth.gateway`, so `hearth/veneer/server.py`
    and `hearth/veneer/protocol.py` no longer exist and the class is
    `Gateway`. Scoped so it does not trip on `hearth/veneer/client.py`, which
    legitimately remains until FTHR-024."""
    import importlib
    from pathlib import Path

    import hearth

    pkg_root = Path(hearth.__file__).parent
    assert not (pkg_root / "veneer" / "server.py").exists()
    assert not (pkg_root / "veneer" / "protocol.py").exists()

    gateway_server = importlib.import_module("hearth.gateway.server")
    gateway_protocol = importlib.import_module("hearth.gateway.protocol")
    assert hasattr(gateway_server, "Gateway")
    assert not hasattr(gateway_server, "Veneer")
    assert hasattr(gateway_protocol, "serialize")


async def test_no_tool_internals_cross_boundary(tmp_path):
    log = EventLog(str(tmp_path / "events.db"))
    loop = _FakeLoop(
        log,
        answer="done answer",
        activities=[("start", "searching"), ("end", "searching")],
    )
    veneer = Veneer(loop, log, config=None)
    server, port = await _serve(veneer)

    try:
        async with websockets.connect(f"ws://127.0.0.1:{port}") as ws:
            messages = await send_turn(ws, "look something up")
    finally:
        server.close()
        await server.wait_closed()

    assert [m["type"] for m in messages] == ["tool_activity", "tool_activity", "answer", "done"]

    whitelists = {
        "tool_activity": {"type", "turn_id", "phase", "label"},
        "answer": {"type", "turn_id", "text"},
        "done": {"type", "turn_id"},
        "error": {"type", "turn_id", "message"},
    }
    forbidden_keys = {"query", "arguments", "observation", "result"}
    for message in messages:
        assert set(message.keys()) <= whitelists[message["type"]]
        assert forbidden_keys.isdisjoint(message.keys())


async def test_loop_error_maps_to_error_message(tmp_path):
    log = EventLog(str(tmp_path / "events.db"))
    loop = _FakeLoop(log, raise_exc=RuntimeError("boom: leaked internal detail"))
    veneer = Veneer(loop, log, config=None)
    server, port = await _serve(veneer)

    try:
        async with websockets.connect(f"ws://127.0.0.1:{port}") as ws:
            messages = await send_turn(ws, "trigger a failure")
    finally:
        server.close()
        await server.wait_closed()

    assert len(messages) == 1
    assert messages[0]["type"] == "error"
    assert "boom" not in messages[0]["message"]
    assert "leaked internal detail" not in messages[0]["message"]

    error_events = [row for row in _event_types(log) if row == "error"]
    assert error_events == ["error"]

async def test_malformed_frame_rejected_connection_survives(tmp_path):
    """A frame that isn't valid JSON (or lacks the request fields) gets a
    curated error reply and a logged event; the same connection then serves
    a normal turn."""
    import json as _json

    log = EventLog(str(tmp_path / "events.db"))
    loop = _FakeLoop(log, answer="still alive")
    veneer = Veneer(loop, log, config=None)
    server, port = await _serve(veneer)

    try:
        async with websockets.connect(f"ws://127.0.0.1:{port}") as ws:
            await ws.send("{not json")
            reply = _json.loads(await ws.recv())
            assert reply == {"type": "error", "turn_id": "", "message": "malformed request"}

            await ws.send(_json.dumps({"turn_id": "t1"}))  # missing final_user_transcript
            reply = _json.loads(await ws.recv())
            assert reply["type"] == "error"
            assert "not json" not in reply["message"]

            messages = await send_turn(ws, "hello again")
    finally:
        server.close()
        await server.wait_closed()

    assert [m["type"] for m in messages] == ["answer", "done"]
    assert messages[0]["text"] == "still alive"

    assert _event_types(log).count("error") == 2
