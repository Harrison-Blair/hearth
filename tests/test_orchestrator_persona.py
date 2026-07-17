"""Orchestrator persona: the Calcifer system prompt leads every turn's first
request, and identity-shaped questions never leave the local tier -- the
identity-leak fix is structural (no tool is ever offered that could route
there), not a prompt patch."""
from __future__ import annotations

import json

import httpx

from conftest import HostRouter
from hearth.brain.router import Router
from hearth.loop import Loop
from hearth.memory.log import EventLog
from hearth.tools.consult import BrainConsult

PERSONA_PROMPT = (
    "You are Calcifer, a small fire demon. Use consult_brain for facts you don't know."
)


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
    def __init__(self, system_prompt: str = PERSONA_PROMPT):
        self.system_prompt = system_prompt


class _Conversation:
    def __init__(self, max_history_turns: int = 12):
        self.max_history_turns = max_history_turns


class _Config:
    def __init__(self):
        self.agent = _Agent()
        self.persona = _Persona()
        self.conversation = _Conversation()


class _FakeRegistry:
    def specs(self):
        return []

    async def dispatch(self, name, args):
        raise KeyError(name)


def _chat_completion(text: str) -> dict:
    return {"choices": [{"message": {"role": "assistant", "content": text}, "finish_reason": "stop"}]}


def _make_router(handler, llm_config):
    backend_config = llm_config.backends["local"]
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url=backend_config.base_url)
    return Router(llm_config, clients={"local": client}), client


async def test_system_prompt_is_first_message(tmp_path, llm_config):
    requests_seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests_seen.append(json.loads(request.content))
        return httpx.Response(200, json=_chat_completion("hi there"))

    router, client = _make_router(handler, llm_config)
    log = EventLog(str(tmp_path / "events.db"))
    consult = BrainConsult(router, _FakeRegistry(), log, _Config())
    loop = Loop(router, log, _Config(), consult=consult)

    await loop.run_turn("s1", "t1", "hello", "chat")

    assert requests_seen[0]["messages"][0] == {"role": "system", "content": PERSONA_PROMPT}

    await client.aclose()


async def test_who_are_you_answers_local_only(tmp_path, two_tier_llm_config):
    def local_handler(request, n):
        return httpx.Response(200, json=_chat_completion("I'm Calcifer."))

    def remote_handler(request, n):
        raise AssertionError("a chat-only turn must never reach the remote tier")

    router_fn = HostRouter({"local-llm.test": local_handler, "remote-llm.test": remote_handler})
    clients = {
        name: httpx.AsyncClient(transport=httpx.MockTransport(router_fn), base_url=backend.base_url)
        for name, backend in two_tier_llm_config.backends.items()
    }
    router = Router(two_tier_llm_config, clients=clients)
    log = EventLog(str(tmp_path / "events.db"))
    consult = BrainConsult(router, _FakeRegistry(), log, _Config())
    loop = Loop(router, log, _Config(), consult=consult)

    answer = await loop.run_turn("s1", "t1", "who are you?", "chat")

    assert answer == "I'm Calcifer."
    assert router_fn.counts["local-llm.test"] == 1
    assert router_fn.counts.get("remote-llm.test", 0) == 0

    for client in clients.values():
        await client.aclose()
