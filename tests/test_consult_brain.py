"""BrainConsult: nested ReAct round on the remote tier over the wikipedia
registry. A `BrainError` (FTHR-008) or a timeout during the consult degrades
to a graceful text observation instead of raising (AC-5)."""
from __future__ import annotations

import asyncio
import json

import httpx

from hearth.brain.base import ToolSpec
from hearth.brain.router import Router
from hearth.config import AgentConfig, PersonaConfig
from hearth.memory.log import EventLog
from hearth.tools.consult import BrainConsult

WIKI_SPEC = ToolSpec(
    name="wikipedia_search",
    description="Search Wikipedia.",
    parameters={"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
    label="search",
)


class _FakeRegistry:
    def __init__(self, observation: str = "Ada Lovelace: a mathematician."):
        self._observation = observation
        self.dispatched = []

    def specs(self):
        return [WIKI_SPEC]

    async def dispatch(self, name: str, args: dict) -> str:
        self.dispatched.append((name, args))
        return self._observation


class _Config:
    def __init__(self, agent: AgentConfig | None = None):
        self.agent = agent or AgentConfig(max_tool_rounds=3, consult_timeout_s=30.0)
        self.persona = PersonaConfig(brain_guard_prompt="Internal research subsystem; no persona.")


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


def _make_router(handler, two_tier_llm_config):
    remote_config = two_tier_llm_config.backends["remote"]
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url=remote_config.base_url)
    return Router(two_tier_llm_config, clients={"remote": client}), client


async def test_consult_runs_nested_react_over_wikipedia(tmp_path, two_tier_llm_config):
    requests_seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests_seen.append(json.loads(request.content))
        if len(requests_seen) == 1:
            return httpx.Response(
                200, json=_tool_call_completion("wikipedia_search", {"query": "Ada Lovelace"})
            )
        return httpx.Response(200, json=_chat_completion("Ada Lovelace was a mathematician."))

    router, client = _make_router(handler, two_tier_llm_config)
    log = EventLog(str(tmp_path / "events.db"))
    registry = _FakeRegistry()
    consult = BrainConsult(router, registry, log, _Config())

    emitted = []

    async def emit(event):
        emitted.append(event)

    result = await consult("s1", "t1", "who was Ada Lovelace", emit=emit)

    assert result == "Ada Lovelace was a mathematician."
    assert registry.dispatched == [("wikipedia_search", {"query": "Ada Lovelace"})]
    assert [(e.phase, e.label) for e in emitted] == [("start", "search"), ("end", "search")]

    events = log.read_session("s1")
    assert [e.type for e in events] == ["tool_call", "observation"]
    assert events[0].payload == {"name": "wikipedia_search", "arguments": {"query": "Ada Lovelace"}}
    assert events[1].payload == {"name": "wikipedia_search", "result": "Ada Lovelace: a mathematician."}

    await client.aclose()


async def test_consult_brain_error_becomes_observation(tmp_path, two_tier_llm_config):
    def handler(request: httpx.Request) -> httpx.Response:
        # Malformed body (no "choices") -> _OpenAICompatBackend raises BrainError.
        return httpx.Response(200, json={"choices": []})

    router, client = _make_router(handler, two_tier_llm_config)
    log = EventLog(str(tmp_path / "events.db"))
    registry = _FakeRegistry()
    consult = BrainConsult(router, registry, log, _Config())

    result = await consult("s1", "t1", "who was Ada Lovelace")

    assert isinstance(result, str)
    assert result
    assert registry.dispatched == []

    await client.aclose()


async def test_consult_timeout_becomes_observation(tmp_path, two_tier_llm_config):
    async def slow_handler(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(1)
        return httpx.Response(200, json=_chat_completion("too slow"))

    remote_config = two_tier_llm_config.backends["remote"]
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(slow_handler), base_url=remote_config.base_url
    )
    router = Router(two_tier_llm_config, clients={"remote": client})
    log = EventLog(str(tmp_path / "events.db"))
    registry = _FakeRegistry()
    consult = BrainConsult(
        router, registry, log, _Config(agent=AgentConfig(max_tool_rounds=3, consult_timeout_s=0.01))
    )

    result = await consult("s1", "t1", "who was Ada Lovelace")

    assert isinstance(result, str)
    assert result

    await client.aclose()
