"""FTHR-010: every nested BrainConsult request carries persona.brain_guard_prompt
as messages[0], ahead of the seeded user query -- config-driven, not hardcoded
(AC-2..4)."""
from __future__ import annotations

import json

import httpx

from hearth.brain.router import Router
from hearth.config import AgentConfig, PersonaConfig
from hearth.memory.log import EventLog
from hearth.tools.consult import BrainConsult


class _FakeRegistry:
    def specs(self):
        return []

    async def dispatch(self, name: str, args: dict) -> str:
        return ""


class _Config:
    def __init__(self, brain_guard_prompt: str):
        self.agent = AgentConfig(max_tool_rounds=3, consult_timeout_s=30.0)
        self.persona = PersonaConfig(brain_guard_prompt=brain_guard_prompt)


def _chat_completion(text: str) -> dict:
    return {"choices": [{"message": {"role": "assistant", "content": text}, "finish_reason": "stop"}]}


def _make_router(handler, two_tier_llm_config):
    remote_config = two_tier_llm_config.backends["remote"]
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url=remote_config.base_url)
    return Router(two_tier_llm_config, clients={"remote": client}), client


async def test_nested_request_carries_guard_as_first_message(tmp_path, two_tier_llm_config):
    requests_seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests_seen.append(json.loads(request.content))
        return httpx.Response(200, json=_chat_completion("ok"))

    router, client = _make_router(handler, two_tier_llm_config)
    log = EventLog(str(tmp_path / "events.db"))
    guard = "You are an internal research subsystem. Do not claim a name or address the user."
    consult = BrainConsult(router, _FakeRegistry(), log, _Config(brain_guard_prompt=guard))

    await consult("s1", "t1", "who was Ada Lovelace")

    sent_messages = requests_seen[0]["messages"]
    assert sent_messages[0] == {"role": "system", "content": guard}
    assert sent_messages[1] == {"role": "user", "content": "who was Ada Lovelace"}

    await client.aclose()


async def test_guard_prompt_is_config_driven(tmp_path, two_tier_llm_config):
    requests_seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests_seen.append(json.loads(request.content))
        return httpx.Response(200, json=_chat_completion("ok"))

    router, client = _make_router(handler, two_tier_llm_config)
    log = EventLog(str(tmp_path / "events.db"))
    guard = "A wholly different guard string, unique to this test."
    consult = BrainConsult(router, _FakeRegistry(), log, _Config(brain_guard_prompt=guard))

    await consult("s1", "t1", "who was Ada Lovelace")

    assert requests_seen[0]["messages"][0]["content"] == guard

    await client.aclose()
