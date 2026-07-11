"""Loop tool rounds: dispatch, observation incorporation, tool-tier routing,
round cap, and content-free ToolActivity emission. Hermetic via MockTransport
and a stubbed ToolRegistry (wikipedia.py itself is tested in test_wikipedia.py)."""
from __future__ import annotations

import json

import httpx

from hearth.brain.base import ToolSpec
from hearth.brain.router import Router
from hearth.events import ToolActivity
from hearth.loop import Loop
from hearth.memory.log import EventLog


SEARCH_SPEC = ToolSpec(
    name="wikipedia_search",
    description="Search Wikipedia and return short summaries.",
    parameters={"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
    label="search",
)


class _FakeRegistry:
    def __init__(self, spec=SEARCH_SPEC, observation: str = "OBSERVATION_TEXT"):
        self._spec = spec
        self._observation = observation
        self.dispatched = []

    def specs(self):
        return [self._spec]

    async def dispatch(self, name: str, args: dict) -> str:
        self.dispatched.append((name, args))
        if name != self._spec.name:
            raise KeyError(f"no tool registered: {name}")
        return self._observation


class _Agent:
    def __init__(self, max_tool_rounds: int = 3, turn_timeout_s: float = 45.0, tool_mode: str = "auto"):
        self.max_tool_rounds = max_tool_rounds
        self.turn_timeout_s = turn_timeout_s
        self.tool_mode = tool_mode


class _Conversation:
    def __init__(self, max_history_turns: int = 12):
        self.max_history_turns = max_history_turns


class _Config:
    def __init__(self, agent: _Agent | None = None, max_history_turns: int = 12):
        self.conversation = _Conversation(max_history_turns)
        self.agent = agent or _Agent()


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


def _make_router(handler, llm_config):
    backend_config = llm_config.backends["local"]
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url=backend_config.base_url)
    return Router(llm_config, client=client), client


async def test_loop_tool_round_incorporates_observation(tmp_path, llm_config, canned_completion):
    requests_seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests_seen.append(json.loads(request.content))
        if len(requests_seen) == 1:
            return httpx.Response(200, json=_tool_call_completion("wikipedia_search", {"query": "Test"}))
        return httpx.Response(200, json=canned_completion(text="Answer based on OBSERVATION_TEXT"))

    router, client = _make_router(handler, llm_config)
    log = EventLog(str(tmp_path / "events.db"))
    registry = _FakeRegistry()
    emitted = []

    async def emit(event):
        emitted.append(event)

    loop = Loop(router, log, _Config(), registry=registry)
    answer = await loop.run_turn("s1", "t1", "look it up", emit=emit)

    assert answer == "Answer based on OBSERVATION_TEXT"
    assert registry.dispatched == [("wikipedia_search", {"query": "Test"})]

    events = log.read_session("s1")
    assert [e.type for e in events] == [
        "user_input",
        "routing_decision",
        "tool_call",
        "observation",
        "final_answer",
    ]
    assert events[2].payload == {"name": "wikipedia_search", "arguments": {"query": "Test"}}
    assert events[3].payload == {"name": "wikipedia_search", "result": "OBSERVATION_TEXT"}

    assert len(emitted) == 2
    assert [(e.phase, e.label) for e in emitted] == [("start", "search"), ("end", "search")]

    # Second request's messages include the tool call + tool result round-trip.
    second_request_roles = [m["role"] for m in requests_seen[1]["messages"]]
    assert "assistant" in second_request_roles
    assert "tool" in second_request_roles

    await client.aclose()


async def test_tool_turn_uses_tool_tier(tmp_path, llm_config, canned_completion):
    requests_seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests_seen.append(json.loads(request.content))
        if len(requests_seen) == 1:
            return httpx.Response(200, json=_tool_call_completion("wikipedia_search", {"query": "Test"}))
        return httpx.Response(200, json=canned_completion(text="final"))

    router, client = _make_router(handler, llm_config)
    log = EventLog(str(tmp_path / "events.db"))
    registry = _FakeRegistry()

    loop = Loop(router, log, _Config(), registry=registry)
    await loop.run_turn("s1", "t1", "look it up")

    events = log.read_session("s1")
    routing = next(e for e in events if e.type == "routing_decision")
    assert routing.payload["tier"] == "tool"

    # First request carried the tool spec.
    assert requests_seen[0]["tools"][0]["function"]["name"] == "wikipedia_search"

    await client.aclose()


async def test_max_tool_rounds_cap(tmp_path, llm_config):
    requests_seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests_seen.append(json.loads(request.content))
        return httpx.Response(200, json=_tool_call_completion("wikipedia_search", {"query": "Test"}))

    router, client = _make_router(handler, llm_config)
    log = EventLog(str(tmp_path / "events.db"))
    registry = _FakeRegistry()

    loop = Loop(router, log, _Config(agent=_Agent(max_tool_rounds=2)), registry=registry)
    answer = await loop.run_turn("s1", "t1", "look it up")

    assert isinstance(answer, str)
    assert answer

    tool_call_events = [e for e in log.read_session("s1") if e.type == "tool_call"]
    assert len(tool_call_events) == 2

    await client.aclose()


async def test_toolactivity_label_only(tmp_path, llm_config, canned_completion):
    requests_seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests_seen.append(json.loads(request.content))
        if len(requests_seen) == 1:
            return httpx.Response(
                200,
                json=_tool_call_completion("wikipedia_search", {"query": "a secret query"}),
            )
        return httpx.Response(200, json=canned_completion(text="final"))

    router, client = _make_router(handler, llm_config)
    log = EventLog(str(tmp_path / "events.db"))
    registry = _FakeRegistry(observation="a secret observation body")
    emitted: list[ToolActivity] = []

    async def emit(event):
        emitted.append(event)

    loop = Loop(router, log, _Config(), registry=registry)
    await loop.run_turn("s1", "t1", "look it up", emit=emit)

    assert len(emitted) == 2
    for event in emitted:
        assert isinstance(event, ToolActivity)
        assert vars(event).keys() == {"turn_id", "phase", "label"}
        assert event.label == "search"
        assert "secret" not in event.label
        assert event.phase in ("start", "end")

    await client.aclose()
