"""Assembled end-to-end integration test: real Veneer + Loop + Router +
ToolRegistry + EventLog, driven over a real WebSocket connection.

Hermetic: the only stubbed boundaries are the LLM backend's HTTP calls and the
Wikipedia REST call, both via `httpx.MockTransport` (same pattern as the unit
tests). Everything else -- `Veneer.serve`, the `websockets` client connection,
`Loop.run_turn`, `Router.select`, `ToolRegistry.dispatch`, `EventLog` -- is the
real production class. This is what proves the pieces already unit-tested in
isolation (FTHR-001..006) actually compose.
"""
from __future__ import annotations

import json

import httpx
import websockets

from hearth.brain.router import Router
from hearth.config import (
    AgentConfig,
    ConversationConfig,
    LLMBackend,
    LLMConfig,
    LLMTiers,
    ToolConfig,
)
from hearth.loop import Loop
from hearth.memory.log import EventLog
from hearth.tools.registry import ToolRegistry
from hearth.veneer.client import send_turn
from hearth.veneer.server import Veneer

WIKI_BODY = {
    "pages": [
        {
            "title": "Ada Lovelace",
            "excerpt": "Ada Lovelace was a mathematician known for work on Babbage's Analytical Engine.",
        }
    ]
}


class _Config:
    """Duck-typed settings object: real per-section config classes (the same
    ones `hearth.config.Settings` composes), assembled without going through
    `Settings`' env/yaml loading so the test controls every value."""

    def __init__(self, llm: LLMConfig, tool: ToolConfig):
        self.llm = llm
        self.tool = tool
        self.agent = AgentConfig(max_tool_rounds=3, turn_timeout_s=45.0, tool_mode="auto")
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
    """Build the real Veneer/Loop/Router/ToolRegistry/EventLog stack, start
    `Veneer.serve` in the background, and return (veneer_task, port, log,
    llm_clients, wiki_client) for the test to drive and tear down."""
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
    registry = ToolRegistry(tool_config=_tool_config(), client=wiki_client)
    config = _Config(llm_config, _tool_config())
    loop = Loop(router, log, config, registry=registry)
    veneer = Veneer(loop, log, config=None)

    server = await websockets.serve(veneer._handle_connection, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    return server, port, log, llm_clients, wiki_client


def _event_types(log: EventLog, session_id: str) -> list[str]:
    return [e.type for e in log.read_session(session_id)]


async def test_e2e_multiturn_chat_and_tool_use(tmp_path):
    """Plain chat turn, then a wikipedia tool-use turn, on the same session,
    driven over a real WebSocket connection with the real Loop/Router/
    ToolRegistry/EventLog wired together (local-only backend)."""
    requests_seen = []

    def llm_handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requests_seen.append(body)
        if len(requests_seen) == 1:
            return httpx.Response(200, json=_chat_completion("hi there"))
        if len(requests_seen) == 2:
            return httpx.Response(
                200, json=_tool_call_completion("wikipedia_search", {"query": "Ada Lovelace"})
            )
        return httpx.Response(
            200, json=_chat_completion("Ada Lovelace was a mathematician.")
        )

    server, port, log, llm_clients, wiki_client = await _assemble(
        _local_only_llm_config(), tmp_path, llm_handler
    )

    try:
        async with websockets.connect(f"ws://127.0.0.1:{port}") as ws:
            turn1_messages = await send_turn(ws, "hello there")
            turn2_messages = await send_turn(ws, "who was Ada Lovelace")
    finally:
        server.close()
        await server.wait_closed()
        for client in llm_clients.values():
            await client.aclose()
        await wiki_client.aclose()

    # --- Turn 1: plain chat, no tool activity on the wire.
    assert [m["type"] for m in turn1_messages] == ["answer", "done"]
    assert turn1_messages[0]["text"] == "hi there"

    # --- Turn 2: tool-use turn -- wire sees exactly start/end tool_activity
    # bracketing the answer, nothing else.
    assert [m["type"] for m in turn2_messages] == [
        "tool_activity",
        "tool_activity",
        "answer",
        "done",
    ]
    assert turn2_messages[0]["phase"] == "start"
    assert turn2_messages[0]["label"] == "search"
    assert turn2_messages[1]["phase"] == "end"
    assert turn2_messages[1]["label"] == "search"
    assert turn2_messages[2]["text"] == "Ada Lovelace was a mathematician."

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
        "observation",
        "final_answer",
    ]

    events = log.read_session(session_id)
    assert events[0].payload == {"text": "hello there"}
    assert events[2].payload == {"text": "hi there"}
    assert events[3].payload == {"text": "who was Ada Lovelace"}
    assert events[5].payload == {"name": "wikipedia_search", "arguments": {"query": "Ada Lovelace"}}
    assert events[6].payload == {
        "name": "wikipedia_search",
        "result": "Ada Lovelace: Ada Lovelace was a mathematician known for work on Babbage's Analytical Engine.",
    }
    assert events[7].payload == {"text": "Ada Lovelace was a mathematician."}

    # History continuity across turns (FC-14): turn 2's first LLM request
    # carries turn 1's user/assistant exchange as prior messages.
    second_turn_first_request = requests_seen[1]
    roles = [m["role"] for m in second_turn_first_request["messages"]]
    contents = [m["content"] for m in second_turn_first_request["messages"]]
    assert roles[:2] == ["user", "assistant"]
    assert contents[:2] == ["hello there", "hi there"]


async def test_e2e_remote_tier_tool_turn_same_shape(tmp_path):
    """Same tool-use turn shape, routed to the remote (OpenRouter-shaped)
    tier -- same wire contract, same event-sequence shape."""
    requests_seen = []

    def llm_handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requests_seen.append(body)
        if len(requests_seen) == 1:
            return httpx.Response(
                200, json=_tool_call_completion("wikipedia_search", {"query": "Ada Lovelace"})
            )
        return httpx.Response(200, json=_chat_completion("Ada Lovelace was a mathematician."))

    server, port, log, llm_clients, wiki_client = await _assemble(
        _local_and_remote_llm_config(remote_enabled=True), tmp_path, llm_handler
    )

    try:
        async with websockets.connect(f"ws://127.0.0.1:{port}") as ws:
            messages = await send_turn(ws, "who was Ada Lovelace")
    finally:
        server.close()
        await server.wait_closed()
        for client in llm_clients.values():
            await client.aclose()
        await wiki_client.aclose()

    assert [m["type"] for m in messages] == ["tool_activity", "tool_activity", "answer", "done"]
    assert messages[2]["text"] == "Ada Lovelace was a mathematician."

    rows = log._conn.execute("SELECT DISTINCT session_id FROM events").fetchall()
    session_id = rows[0][0]
    assert _event_types(log, session_id) == [
        "user_input",
        "routing_decision",
        "tool_call",
        "observation",
        "final_answer",
    ]
    routing = next(e for e in log.read_session(session_id) if e.type == "routing_decision")
    assert routing.payload["tier"] == "tool"
    assert routing.payload["backend_name"] == "remote"

    # The remote-shaped request carried the remote model id -- proves it
    # actually went to the "remote" backend, not just that routing said so.
    assert requests_seen[0]["model"] == "openrouter/free"


async def test_e2e_remote_disabled_stays_local(tmp_path):
    """`remote.enabled=false`: the tool-use turn still resolves to the local
    tier end-to-end, over the real socket."""
    requests_seen = []

    def llm_handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requests_seen.append(body)
        if len(requests_seen) == 1:
            return httpx.Response(
                200, json=_tool_call_completion("wikipedia_search", {"query": "Ada Lovelace"})
            )
        return httpx.Response(200, json=_chat_completion("Ada Lovelace was a mathematician."))

    server, port, log, llm_clients, wiki_client = await _assemble(
        _local_and_remote_llm_config(remote_enabled=False), tmp_path, llm_handler
    )

    try:
        async with websockets.connect(f"ws://127.0.0.1:{port}") as ws:
            messages = await send_turn(ws, "who was Ada Lovelace")
    finally:
        server.close()
        await server.wait_closed()
        for client in llm_clients.values():
            await client.aclose()
        await wiki_client.aclose()

    assert [m["type"] for m in messages] == ["tool_activity", "tool_activity", "answer", "done"]

    rows = log._conn.execute("SELECT DISTINCT session_id FROM events").fetchall()
    session_id = rows[0][0]
    routing = next(e for e in log.read_session(session_id) if e.type == "routing_decision")
    assert routing.payload["backend_name"] == "local"
    assert requests_seen[0]["model"] == "qwen3:14b"
