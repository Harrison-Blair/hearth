"""Loop/consult_brain: the orchestrator offers only `consult_brain` at the
local tier; a `consult_brain` call drives a nested ReAct round on the remote
tier over the wikipedia registry, whose result becomes the orchestrator's
own observation. `wikipedia_search` is never offered at the top level.
Hermetic via a host-keyed MockTransport (local vs remote)."""
from __future__ import annotations

import json

import httpx

from conftest import HostRouter
from hearth.brain.base import ToolSpec
from hearth.brain.router import Router
from hearth.loop import Loop
from hearth.memory.log import EventLog
from hearth.tools.consult import BrainConsult

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
    def __init__(
        self,
        max_consult_rounds: int = 3,
        max_tool_rounds: int = 3,
        turn_timeout_s: float = 45.0,
        consult_timeout_s: float = 30.0,
        tool_mode: str = "auto",
    ):
        self.max_consult_rounds = max_consult_rounds
        self.max_tool_rounds = max_tool_rounds
        self.turn_timeout_s = turn_timeout_s
        self.consult_timeout_s = consult_timeout_s
        self.tool_mode = tool_mode


class _Persona:
    def __init__(
        self,
        system_prompt: str = "You are Calcifer.",
        brain_guard_prompt: str = "Internal research subsystem; no persona.",
    ):
        self.system_prompt = system_prompt
        self.brain_guard_prompt = brain_guard_prompt


class _Conversation:
    def __init__(self, max_history_turns: int = 12):
        self.max_history_turns = max_history_turns


class _Config:
    def __init__(self, agent: _Agent | None = None, persona: _Persona | None = None, max_history_turns: int = 12):
        self.conversation = _Conversation(max_history_turns)
        self.agent = agent or _Agent()
        self.persona = persona or _Persona()


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
    return {"choices": [{"message": {"role": "assistant", "content": text}, "finish_reason": "stop"}]}


def _build(two_tier_llm_config, local_handler, remote_handler):
    router_fn = HostRouter({"local-llm.test": local_handler, "remote-llm.test": remote_handler})
    clients = {
        name: httpx.AsyncClient(transport=httpx.MockTransport(router_fn), base_url=backend.base_url)
        for name, backend in two_tier_llm_config.backends.items()
    }
    router = Router(two_tier_llm_config, clients=clients)
    return router, clients, router_fn


async def test_orchestrator_first_request_offers_consult_brain_at_default_tier(
    tmp_path, two_tier_llm_config
):
    requests_seen = []

    def local_handler(request, n):
        requests_seen.append(json.loads(request.content))
        return httpx.Response(200, json=_chat_completion("hi there"))

    def remote_handler(request, n):
        raise AssertionError("remote should not be called for a plain chat turn")

    router, clients, router_fn = _build(two_tier_llm_config, local_handler, remote_handler)
    log = EventLog(str(tmp_path / "events.db"))
    registry = _FakeRegistry()
    consult = BrainConsult(router, registry, log, _Config())

    loop = Loop(router, log, _Config(), consult=consult)
    answer = await loop.run_turn("s1", "t1", "hello")

    assert answer == "hi there"
    assert router_fn.counts["local-llm.test"] == 1
    assert router_fn.counts.get("remote-llm.test", 0) == 0

    tool_names = [t["function"]["name"] for t in requests_seen[0].get("tools", [])]
    assert tool_names == ["consult_brain"]

    routing = next(e for e in log.read_session("s1") if e.type == "routing_decision")
    assert routing.payload["tier"] == "default"
    assert routing.payload["backend_name"] == "local"

    for client in clients.values():
        await client.aclose()


async def test_consult_dispatches_nested_wikipedia_search(tmp_path, two_tier_llm_config):
    def local_handler(request, n):
        if n == 1:
            return httpx.Response(
                200, json=_tool_call_completion("consult_brain", {"query": "Ada Lovelace"})
            )
        return httpx.Response(200, json=_chat_completion("Ada Lovelace was a mathematician."))

    def remote_handler(request, n):
        if n == 1:
            return httpx.Response(
                200, json=_tool_call_completion("wikipedia_search", {"query": "Ada Lovelace"})
            )
        return httpx.Response(200, json=_chat_completion("Findings: Ada Lovelace, mathematician."))

    router, clients, router_fn = _build(two_tier_llm_config, local_handler, remote_handler)
    log = EventLog(str(tmp_path / "events.db"))
    registry = _FakeRegistry()
    consult = BrainConsult(router, registry, log, _Config())

    loop = Loop(router, log, _Config(), consult=consult)
    emitted = []

    async def emit(event):
        emitted.append(event)

    answer = await loop.run_turn("s1", "t1", "who was Ada Lovelace", emit=emit)

    assert answer == "Ada Lovelace was a mathematician."
    assert registry.dispatched == [("wikipedia_search", {"query": "Ada Lovelace"})]
    assert router_fn.counts["local-llm.test"] == 2
    assert router_fn.counts["remote-llm.test"] == 2

    assert [(e.phase, e.label) for e in emitted] == [
        ("start", "consult"),
        ("start", "search"),
        ("end", "search"),
        ("end", "consult"),
    ]

    events = log.read_session("s1")
    assert [e.type for e in events] == [
        "user_input",
        "routing_decision",
        "tool_call",
        "tool_call",
        "observation",
        "observation",
        "final_answer",
    ]
    assert events[2].payload == {"name": "consult_brain", "arguments": {"query": "Ada Lovelace"}}
    assert events[3].payload == {"name": "wikipedia_search", "arguments": {"query": "Ada Lovelace"}}
    assert events[4].payload == {"name": "wikipedia_search", "result": "OBSERVATION_TEXT"}
    assert events[5].payload == {"name": "consult_brain", "result": "Findings: Ada Lovelace, mathematician."}

    for client in clients.values():
        await client.aclose()


async def test_wikipedia_search_never_offered_at_top_level(tmp_path, two_tier_llm_config):
    def local_handler(request, n):
        body = json.loads(request.content)
        tool_names = [t["function"]["name"] for t in body.get("tools", [])]
        assert "wikipedia_search" not in tool_names
        return httpx.Response(200, json=_chat_completion("hi"))

    def remote_handler(request, n):
        raise AssertionError("remote should not be called")

    router, clients, router_fn = _build(two_tier_llm_config, local_handler, remote_handler)
    log = EventLog(str(tmp_path / "events.db"))
    registry = _FakeRegistry()
    consult = BrainConsult(router, registry, log, _Config())
    loop = Loop(router, log, _Config(), consult=consult)

    await loop.run_turn("s1", "t1", "hello")

    for client in clients.values():
        await client.aclose()


async def test_nested_tool_round_cap(tmp_path, two_tier_llm_config):
    def local_handler(request, n):
        if n == 1:
            return httpx.Response(200, json=_tool_call_completion("consult_brain", {"query": "x"}))
        return httpx.Response(200, json=_chat_completion("done"))

    def remote_handler(request, n):
        return httpx.Response(200, json=_tool_call_completion("wikipedia_search", {"query": "x"}))

    router, clients, router_fn = _build(two_tier_llm_config, local_handler, remote_handler)
    log = EventLog(str(tmp_path / "events.db"))
    registry = _FakeRegistry()
    consult_config = _Config(agent=_Agent(max_tool_rounds=2))
    consult = BrainConsult(router, registry, log, consult_config)

    loop = Loop(router, log, _Config(), consult=consult)
    answer = await loop.run_turn("s1", "t1", "look it up")

    assert isinstance(answer, str)
    assert answer

    tool_call_events = [e for e in log.read_session("s1") if e.type == "tool_call"]
    nested_calls = [e for e in tool_call_events if e.payload["name"] == "wikipedia_search"]
    assert len(nested_calls) == 2

    for client in clients.values():
        await client.aclose()
