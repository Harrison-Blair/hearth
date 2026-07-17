"""FTHR-026: proof that the engine serves multiple veneers at once (FC-5),
isolates their conversations (FC-6), and does not serialize turns across them
(FC-7).

These three properties already hold by construction (a fresh `session_id` per
connection, a stateless/reentrant `Loop`, per-session history reconstruction),
but nothing enforces them and, with a single surface, none of them is
observable. This module turns them into guarded properties before the audio
plumages depend on them. It adds NO production code: the "second veneer" is a
test-local fake client (two simultaneous loopback websocket connections against
a real `Gateway`), matching the `_serve` helper in `test_gateway.py` and the
fake-`Loop` shape in `test_e2e_gateway.py`.

Because the behavior already exists, the tests pass on first run; each was
verified per the repo's standing rule for feature tests -- break the property,
observe the test fail for the right reason, restore -- and that break/restore is
recorded in `.fledge/molt/FTHR-026.md`.
"""
from __future__ import annotations

import asyncio
import json

import httpx
import websockets

from hearth.brain.router import Router
from hearth.gateway.server import Gateway
from hearth.loop import Loop
from hearth.memory.log import EventLog
from hearth.veneers.base import send_turn

# A generous bound for a loopback round trip. Its only job is to turn a
# serializing/stalled engine into a clean, legible timeout instead of a hung
# suite -- the happy path finishes in milliseconds.
TIMEOUT_S = 5.0


async def _serve(gateway):
    """Start a loopback server for `gateway` on an ephemeral port; return the
    running server and its port (same shape as `test_gateway.py::_serve`)."""
    server = await websockets.serve(gateway._handle_connection, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    return server, port


async def _close(server) -> None:
    """Shut the loopback server down, bounding `wait_closed()` so a turn stuck
    inside the engine (the very failure these tests probe for) surfaces as the
    body's clean timeout rather than a hung suite -- the legible-failure
    property the FC-7 test is built around."""
    server.close()
    try:
        await asyncio.wait_for(server.wait_closed(), timeout=TIMEOUT_S)
    except asyncio.TimeoutError:
        pass


# --- FC-5: two veneers served concurrently ---------------------------------


class _BarrierLoop:
    """Fake `Loop` that will not answer ANY turn until `parties` turns are in
    flight at once. A turn logs its input, then parks until the barrier fills;
    only when both connections are being served concurrently does either turn
    return. A serialized engine -- or a stalled/refused second connection --
    never fills the barrier, so the bounded wait times out. This is what makes
    the test prove simultaneity rather than mere reuse."""

    def __init__(self, log, parties: int = 2) -> None:
        self._log = log
        self._parties = parties
        self._arrived = 0
        self._all_here = asyncio.Event()

    async def run_turn(self, session_id, turn_id, transcript, emit=None):
        self._log.append(session_id, turn_id, "user_input", "user", {"text": transcript})
        self._arrived += 1
        if self._arrived >= self._parties:
            self._all_here.set()
        await self._all_here.wait()
        answer = f"served {session_id}"
        self._log.append(session_id, turn_id, "final_answer", "brain", {"text": answer})
        return answer


async def test_two_veneers_connected_concurrently_are_both_served(tmp_path):
    """FC-5 / PLM-007 AC-5: two connections are open SIMULTANEOUSLY -- neither
    closed before the other opens -- and both are served. The barrier loop
    only answers once both turns are in flight, so a green result is proof of
    concurrent service, not of sequential connect/turn/close."""
    log = EventLog(str(tmp_path / "events.db"))
    gateway = Gateway(_BarrierLoop(log, parties=2), log, config=None)
    server, port = await _serve(gateway)
    url = f"ws://127.0.0.1:{port}"

    try:
        async with (
            websockets.connect(url) as ws_a,
            websockets.connect(url) as ws_b,
        ):
            # Both connections are open here; neither turn can complete until
            # the other is also being served.
            msgs_a, msgs_b = await asyncio.wait_for(
                asyncio.gather(send_turn(ws_a, "from A"), send_turn(ws_b, "from B")),
                timeout=TIMEOUT_S,
            )
    finally:
        await _close(server)

    assert [m["type"] for m in msgs_a] == ["answer", "done"]
    assert [m["type"] for m in msgs_b] == ["answer", "done"]
    # Distinct per-connection session ids -> distinct answer texts: both
    # connections were served as independent sessions.
    assert msgs_a[0]["text"] != msgs_b[0]["text"]


# --- FC-6: isolated conversations ------------------------------------------


class _Conversation:
    def __init__(self, max_history_turns: int) -> None:
        self.max_history_turns = max_history_turns


class _Agent:
    def __init__(self, max_consult_rounds: int = 3, turn_timeout_s: float = 45.0) -> None:
        self.max_consult_rounds = max_consult_rounds
        self.turn_timeout_s = turn_timeout_s


class _Persona:
    def __init__(self, system_prompt: str = "You are Calcifer.") -> None:
        self.system_prompt = system_prompt


class _Config:
    """Minimal duck-typed config for the real `Loop` (same shape as
    `test_loop.py::_Config`) -- only the fields `run_turn` reads."""

    def __init__(self, max_history_turns: int = 12) -> None:
        self.conversation = _Conversation(max_history_turns)
        self.agent = _Agent()
        self.persona = _Persona()


async def test_concurrent_veneers_hold_isolated_conversations(tmp_path, llm_config):
    """FC-6 / PLM-007 AC-6: a turn on one concurrently-connected veneer does
    not enter another's conversation. Asserted on the messages the BACKEND
    receives (where reconstructed history would leak), not merely on session
    ids -- a session-id check would pass even if history bled across."""
    requests_seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requests_seen.append(body)
        answer = f"answer {len(requests_seen)}"
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"role": "assistant", "content": answer}, "finish_reason": "stop"}
                ]
            },
        )

    backend_config = llm_config.backends["local"]
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url=backend_config.base_url
    )
    router = Router(llm_config, clients={"local": client})
    log = EventLog(str(tmp_path / "events.db"))
    gateway = Gateway(Loop(router, log, _Config()), log, config=None)
    server, port = await _serve(gateway)
    url = f"ws://127.0.0.1:{port}"

    alpha = "ALPHA-CANARY-9f3a1"
    bravo = "BRAVO-CANARY-2b7c4"

    try:
        # Both veneers connected at once; A's turn completes, then B's, with
        # neither connection closed. A finishing first is deliberate: it puts
        # A's input in the log before B reconstructs, so the isolation claim is
        # tested against the worst case for leakage.
        async with (
            websockets.connect(url) as ws_a,
            websockets.connect(url) as ws_b,
        ):
            msgs_a = await send_turn(ws_a, alpha)
            msgs_b = await send_turn(ws_b, bravo)
    finally:
        await _close(server)
        await client.aclose()

    assert [m["type"] for m in msgs_a] == ["answer", "done"]
    assert [m["type"] for m in msgs_b] == ["answer", "done"]

    # The request(s) the backend saw for B's turn are those carrying B's text.
    b_requests = [
        req for req in requests_seen if any(m.get("content") == bravo for m in req["messages"])
    ]
    assert b_requests, requests_seen
    # A's text must appear nowhere in what the backend received for B's turn.
    for req in b_requests:
        assert alpha not in json.dumps(req["messages"])
    # And A's text WAS on the wire for A's own turn -- guards against a false
    # pass where the canary simply never reached any backend request.
    assert any(
        any(m.get("content") == alpha for m in req["messages"]) for req in requests_seen
    ), requests_seen


# --- FC-7: turns are not serialized across veneers -------------------------


class _GatedLoop:
    """Fake `Loop` whose turn 'A' cannot complete until turn 'B' has: A parks
    on an event that B sets on its way out. Under a correctly non-serializing
    engine, B runs while A is parked and both finish. Under a serializing
    engine this CANNOT pass -- B is queued behind the A that waits for it, so
    the turn deadlocks and the bounded wait times out. A test that cannot pass
    when the property breaks, rather than one that merely happens to pass."""

    def __init__(self, log) -> None:
        self._log = log
        self._b_done = asyncio.Event()

    async def run_turn(self, session_id, turn_id, transcript, emit=None):
        self._log.append(session_id, turn_id, "user_input", "user", {"text": transcript})
        if transcript.startswith("A"):
            await self._b_done.wait()  # gated on B's completion
            answer = "A completed after B"
        else:
            answer = "B completed first"
            self._b_done.set()  # release the parked A
        self._log.append(session_id, turn_id, "final_answer", "brain", {"text": answer})
        return answer


async def test_engine_does_not_serialize_turns_across_veneers(tmp_path):
    """FC-7 / PLM-007 AC-7: concurrent turns from two surfaces are each served
    with no engine-side serialization. Turn A is gated on turn B's completion;
    both finish within a bounded timeout. A serializing engine deadlocks here
    and the wait times out, so this cannot be a green rubber stamp."""
    log = EventLog(str(tmp_path / "events.db"))
    gateway = Gateway(_GatedLoop(log), log, config=None)
    server, port = await _serve(gateway)
    url = f"ws://127.0.0.1:{port}"

    try:
        async with (
            websockets.connect(url) as ws_a,
            websockets.connect(url) as ws_b,
        ):
            msgs_a, msgs_b = await asyncio.wait_for(
                asyncio.gather(send_turn(ws_a, "A gated on B"), send_turn(ws_b, "B first")),
                timeout=TIMEOUT_S,
            )
    finally:
        await _close(server)

    assert [m["type"] for m in msgs_a] == ["answer", "done"]
    assert [m["type"] for m in msgs_b] == ["answer", "done"]
    assert msgs_a[0]["text"] == "A completed after B"
    assert msgs_b[0]["text"] == "B completed first"
