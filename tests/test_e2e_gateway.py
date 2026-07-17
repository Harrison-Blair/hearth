"""Assembled end-to-end integration test: real Gateway + Loop + Router +
BrainConsult + ToolRegistry + EventLog, driven over a real WebSocket
connection.

Hermetic: the only stubbed boundaries are the LLM backends' HTTP calls and
the Wikipedia REST call, both via `httpx.MockTransport` (same pattern as the
unit tests). Everything else -- `Gateway.serve`, the `websockets` client
connection, `Loop.run_turn`, `Router.select`, `BrainConsult.__call__`,
`ToolRegistry.dispatch`, `EventLog` -- is the real production class. This is
what proves the pieces already unit-tested in isolation (FTHR-001..009)
actually compose: the local orchestrator carries the persona system prompt
and offers only `consult_brain`; a `consult_brain` call nests a real
`wikipedia_search` round on the tool tier.
"""
from __future__ import annotations

import asyncio
import json

import httpx
import websockets

from conftest import HostRouter
from hearth.brain.router import Router
from hearth.config import (
    AgentConfig,
    ConversationConfig,
    LLMBackend,
    LLMConfig,
    LLMTiers,
    PersonaConfig,
    ToolConfig,
)
from hearth.loop import Loop
from hearth.memory.log import EventLog
from hearth.tools.consult import BrainConsult
from hearth.tools.registry import ToolRegistry
from hearth.veneers.base import send_turn
from hearth.gateway.server import Gateway

WIKI_BODY = {
    "pages": [
        {
            "title": "Ada Lovelace",
            "excerpt": "Ada Lovelace was a mathematician known for work on Babbage's Analytical Engine.",
        }
    ]
}

PERSONA_PROMPT = "You are Calcifer, a small fire demon."


class _Config:
    """Duck-typed settings object: real per-section config classes (the same
    ones `hearth.config.Settings` composes), assembled without going through
    `Settings`' env/yaml loading so the test controls every value."""

    def __init__(self, llm: LLMConfig, tool: ToolConfig):
        self.llm = llm
        self.tool = tool
        self.agent = AgentConfig(
            max_tool_rounds=3,
            turn_timeout_s=45.0,
            tool_mode="auto",
            max_consult_rounds=3,
            consult_timeout_s=30.0,
        )
        self.persona = PersonaConfig(enabled=True, system_prompt=PERSONA_PROMPT)
        self.conversation = ConversationConfig(max_history_turns=12)


def _local_only_llm_config() -> LLMConfig:
    return LLMConfig(
        backends={
            "local": LLMBackend(
                base_url="http://local-llm.test/v1",
                model="qwen3:14b",
                api_key_env=None,
                supports_tools=True,
                supports_streaming=True,
                context_window=8192,
                cost_tier="free",
                enabled=True,
            )
        },
        tiers=LLMTiers(default="local", tool="local"),
        timeout=60.0,
        max_retries=2,
    )


def _local_and_remote_llm_config(remote_enabled: bool) -> LLMConfig:
    return LLMConfig(
        backends={
            "local": LLMBackend(
                base_url="http://local-llm.test/v1",
                model="qwen3:14b",
                api_key_env=None,
                supports_tools=True,
                supports_streaming=True,
                context_window=8192,
                cost_tier="free",
                enabled=True,
            ),
            "remote": LLMBackend(
                base_url="https://openrouter.test/api/v1",
                model="openrouter/free",
                api_key_env="HEARTH_LLM__OPENROUTER_API_KEY",
                supports_tools=True,
                supports_streaming=True,
                context_window=8192,
                cost_tier="free",
                enabled=remote_enabled,
            ),
        },
        tiers=LLMTiers(default="local", tool="remote"),
        timeout=60.0,
        max_retries=2,
    )


def _tool_config() -> ToolConfig:
    return ToolConfig(
        wikipedia_enabled=True,
        wikipedia_language="en",
        wikipedia_endpoint="/w/rest.php/v1/search/page",
        wikipedia_result_count=3,
        wikipedia_max_chars=1000,
        wikipedia_timeout=10.0,
    )


def _tool_call_completion(name: str, arguments: dict, call_id: str = "call_1") -> dict:
    return {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": call_id,
                            "type": "function",
                            "function": {"name": name, "arguments": json.dumps(arguments)},
                        }
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ]
    }


def _chat_completion(text: str) -> dict:
    return {
        "choices": [
            {
                "message": {"role": "assistant", "content": text},
                "finish_reason": "stop",
            }
        ]
    }


def _wiki_client() -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=WIKI_BODY)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://wiki.test")


async def _assemble(llm_config: LLMConfig, tmp_path, llm_handler):
    """Build the real Gateway/Loop/Router/BrainConsult/ToolRegistry/EventLog
    stack, start `Gateway.serve` in the background, and return
    (gateway_task, port, log, llm_clients, wiki_client) for the test to drive
    and tear down."""
    # Mirrors `hearth.app`'s daemon wiring: one client per backend, each
    # bound to that backend's own base_url.
    llm_clients = {
        name: httpx.AsyncClient(
            transport=httpx.MockTransport(llm_handler), base_url=backend.base_url
        )
        for name, backend in llm_config.backends.items()
    }
    wiki_client = _wiki_client()

    log = EventLog(str(tmp_path / "events.db"))
    router = Router(llm_config, clients=llm_clients)
    # Wikipedia lives brain-side only: reachable exclusively through a
    # `consult_brain` call's nested ReAct loop, never offered at top level.
    wiki_registry = ToolRegistry(tool_config=_tool_config(), client=wiki_client)
    config = _Config(llm_config, _tool_config())
    consult = BrainConsult(router, wiki_registry, log, config)
    loop = Loop(router, log, config, consult=consult)
    gateway = Gateway(loop, log, config=None)

    server = await websockets.serve(gateway._handle_connection, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    return server, port, log, llm_clients, wiki_client


def _event_types(log: EventLog, session_id: str) -> list[str]:
    return [e.type for e in log.read_session(session_id)]


async def test_e2e_multiturn_chat_and_consult(tmp_path):
    """Plain chat turn, then a `consult_brain` turn that nests a real
    wikipedia lookup, driven over a real WebSocket connection with the real
    Loop/Router/BrainConsult/ToolRegistry/EventLog wired together
    (local-only backend serving both tiers)."""
    requests_seen = []

    def llm_handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requests_seen.append(body)
        n = len(requests_seen)
        if n == 1:
            return httpx.Response(200, json=_chat_completion("hi there"))
        if n == 2:
            return httpx.Response(
                200, json=_tool_call_completion("consult_brain", {"query": "Ada Lovelace"})
            )
        if n == 3:
            return httpx.Response(
                200, json=_tool_call_completion("wikipedia_search", {"query": "Ada Lovelace"})
            )
        if n == 4:
            return httpx.Response(
                200, json=_chat_completion("Findings: Ada Lovelace was a mathematician.")
            )
        return httpx.Response(200, json=_chat_completion("Ada Lovelace was a mathematician."))

    server, port, log, llm_clients, wiki_client = await _assemble(
        _local_only_llm_config(), tmp_path, llm_handler
    )

    try:
        async with websockets.connect(f"ws://127.0.0.1:{port}") as ws:
            turn1_messages = await send_turn(ws, "hello there", "chat")
            turn2_messages = await send_turn(ws, "who was Ada Lovelace", "chat")
    finally:
        server.close()
        await server.wait_closed()
        for client in llm_clients.values():
            await client.aclose()
        await wiki_client.aclose()

    # --- Turn 1: plain chat, no tool activity on the wire.
    assert [m["type"] for m in turn1_messages] == ["answer", "done"]
    assert turn1_messages[0]["text"] == "hi there"

    # --- Turn 2: consult-brain turn -- wire sees consult start/end
    # bracketing a nested search start/end, then the answer.
    assert [m["type"] for m in turn2_messages] == [
        "tool_activity",
        "tool_activity",
        "tool_activity",
        "tool_activity",
        "answer",
        "done",
    ]
    assert [(m["phase"], m["label"]) for m in turn2_messages[:4]] == [
        ("start", "consult"),
        ("start", "search"),
        ("end", "search"),
        ("end", "consult"),
    ]
    assert turn2_messages[4]["text"] == "Ada Lovelace was a mathematician."

    whitelists = {
        "tool_activity": {"type", "turn_id", "phase", "label"},
        "answer": {"type", "turn_id", "text"},
        "done": {"type", "turn_id"},
    }
    forbidden_keys = {"query", "arguments", "observation", "result"}
    for message in turn1_messages + turn2_messages:
        assert set(message.keys()) <= whitelists[message["type"]]
        assert forbidden_keys.isdisjoint(message.keys())

    # --- Both turns landed in the same session's event log, in order, with
    # the full expected event set and multi-turn history intact.
    rows = log._conn.execute("SELECT DISTINCT session_id FROM events").fetchall()
    assert len(rows) == 1
    session_id = rows[0][0]

    assert _event_types(log, session_id) == [
        "user_input",
        "routing_decision",
        "final_answer",
        "user_input",
        "routing_decision",
        "tool_call",
        "tool_call",
        "observation",
        "observation",
        "final_answer",
    ]

    events = log.read_session(session_id)
    assert events[0].payload == {"text": "hello there"}
    assert events[2].payload == {"text": "hi there"}
    assert events[3].payload == {"text": "who was Ada Lovelace"}
    assert events[5].payload == {"name": "consult_brain", "arguments": {"query": "Ada Lovelace"}}
    assert events[6].payload == {"name": "wikipedia_search", "arguments": {"query": "Ada Lovelace"}}
    assert events[7].payload == {
        "name": "wikipedia_search",
        "result": "Ada Lovelace: Ada Lovelace was a mathematician known for work on Babbage's Analytical Engine.",
    }
    assert events[8].payload == {
        "name": "consult_brain",
        "result": "Findings: Ada Lovelace was a mathematician.",
    }
    assert events[9].payload == {"text": "Ada Lovelace was a mathematician."}

    # Persona + history continuity across turns: turn 2's first LLM request
    # carries the persona system prompt as messages[0], then turn 1's
    # user/assistant exchange (FC-14).
    second_turn_first_request = requests_seen[1]
    roles = [m["role"] for m in second_turn_first_request["messages"]]
    contents = [m["content"] for m in second_turn_first_request["messages"]]
    assert roles[0] == "system"
    assert contents[0] == PERSONA_PROMPT
    assert roles[1:3] == ["user", "assistant"]
    assert contents[1:3] == ["hello there", "hi there"]


async def test_e2e_remote_tier_consult_same_shape(tmp_path):
    """Same consult-turn shape, but the nested consult genuinely reaches a
    separate remote (OpenRouter-shaped) backend -- proves the tier split is
    real, not just same-backend reuse."""

    def local_handler(request: httpx.Request, n: int) -> httpx.Response:
        body = json.loads(request.content)
        assert body["model"] == "qwen3:14b"
        if n == 1:
            return httpx.Response(
                200, json=_tool_call_completion("consult_brain", {"query": "Ada Lovelace"})
            )
        return httpx.Response(200, json=_chat_completion("Ada Lovelace was a mathematician."))

    def remote_handler(request: httpx.Request, n: int) -> httpx.Response:
        body = json.loads(request.content)
        assert body["model"] == "openrouter/free"
        if n == 1:
            return httpx.Response(
                200, json=_tool_call_completion("wikipedia_search", {"query": "Ada Lovelace"})
            )
        return httpx.Response(
            200, json=_chat_completion("Findings: Ada Lovelace was a mathematician.")
        )

    router_fn = HostRouter({"local-llm.test": local_handler, "openrouter.test": remote_handler})

    server, port, log, llm_clients, wiki_client = await _assemble(
        _local_and_remote_llm_config(remote_enabled=True), tmp_path, router_fn
    )

    try:
        async with websockets.connect(f"ws://127.0.0.1:{port}") as ws:
            messages = await send_turn(ws, "who was Ada Lovelace", "chat")
    finally:
        server.close()
        await server.wait_closed()
        for client in llm_clients.values():
            await client.aclose()
        await wiki_client.aclose()

    assert [m["type"] for m in messages] == [
        "tool_activity",
        "tool_activity",
        "tool_activity",
        "tool_activity",
        "answer",
        "done",
    ]
    assert [(m["phase"], m["label"]) for m in messages[:4]] == [
        ("start", "consult"),
        ("start", "search"),
        ("end", "search"),
        ("end", "consult"),
    ]
    assert messages[4]["text"] == "Ada Lovelace was a mathematician."

    rows = log._conn.execute("SELECT DISTINCT session_id FROM events").fetchall()
    session_id = rows[0][0]
    assert _event_types(log, session_id) == [
        "user_input",
        "routing_decision",
        "tool_call",
        "tool_call",
        "observation",
        "observation",
        "final_answer",
    ]
    routing = next(e for e in log.read_session(session_id) if e.type == "routing_decision")
    assert routing.payload["tier"] == "default"
    assert routing.payload["backend_name"] == "local"

    assert router_fn.counts["local-llm.test"] == 2
    assert router_fn.counts["openrouter.test"] == 2


async def test_e2e_remote_disabled_stays_local_chat_only(tmp_path):
    """AC-6: with the remote/brain disabled, `consult_brain` is not offered
    at all -- the turn is pure local chat, no tool_activity on the wire, and
    it never crashes."""
    requests_seen = []

    def llm_handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requests_seen.append(body)
        tool_names = [t["function"]["name"] for t in body.get("tools", [])]
        assert tool_names == []
        return httpx.Response(200, json=_chat_completion("I can only use what I already know."))

    server, port, log, llm_clients, wiki_client = await _assemble(
        _local_and_remote_llm_config(remote_enabled=False), tmp_path, llm_handler
    )

    try:
        async with websockets.connect(f"ws://127.0.0.1:{port}") as ws:
            messages = await send_turn(ws, "who was Ada Lovelace", "chat")
    finally:
        server.close()
        await server.wait_closed()
        for client in llm_clients.values():
            await client.aclose()
        await wiki_client.aclose()

    assert [m["type"] for m in messages] == ["answer", "done"]

    rows = log._conn.execute("SELECT DISTINCT session_id FROM events").fetchall()
    session_id = rows[0][0]
    routing = next(e for e in log.read_session(session_id) if e.type == "routing_decision")
    assert routing.payload["backend_name"] == "local"
    assert requests_seen[0]["model"] == "qwen3:14b"


class _SlowFakeLoop:
    """A minimal `Loop` double (same shape as test_gateway.py's `_FakeLoop`)
    that delays before returning, giving a client time to disconnect mid-turn
    so the server's reply `send()` hits a closed socket."""

    def __init__(self, log):
        self._log = log

    async def run_turn(self, session_id, turn_id, transcript, surface, emit=None):
        self._log.append(session_id, turn_id, "user_input", surface, {"text": transcript})
        await asyncio.sleep(0.1)
        self._log.append(session_id, turn_id, "final_answer", "brain", {"text": "answer"})
        return "answer"


async def test_serve_continues_after_one_connection_disconnects(tmp_path):
    """AC-5: a client that disconnects mid-turn is handled cleanly rather
    than taking the server down -- a later connection still completes a
    normal turn against the same running server."""
    log = EventLog(str(tmp_path / "events.db"))
    gateway = Gateway(_SlowFakeLoop(log), log, config=None)

    server = await websockets.serve(gateway._handle_connection, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]

    try:
        ws1 = await websockets.connect(f"ws://127.0.0.1:{port}")
        await ws1.send(
            json.dumps(
                {
                    "turn_id": "t1",
                    "final_user_transcript": "disconnecting",
                    "surface": "chat",
                }
            )
        )
        await ws1.close()  # client gone before the server's reply send()

        # Give the server a moment to hit the send-after-close and recover.
        await asyncio.sleep(0.3)

        async with websockets.connect(f"ws://127.0.0.1:{port}") as ws2:
            messages = await send_turn(ws2, "second, should complete normally", "chat")
    finally:
        server.close()
        await server.wait_closed()

    assert [m["type"] for m in messages] == ["answer", "done"]
    assert messages[0]["text"] == "answer"
