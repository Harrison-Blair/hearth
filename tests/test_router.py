"""Router.select: deterministic, config-driven tier routing with gating and override."""
from __future__ import annotations

import httpx
import pytest

from hearth.brain.router import Router
from hearth.config import LLMBackend, LLMConfig, LLMTiers


def make_config(remote_enabled: bool = True) -> LLMConfig:
    return LLMConfig(
        backends={
            "local": LLMBackend(
                base_url="http://localhost:11434/v1",
                model="qwen3:14b",
                api_key_env=None,
                supports_tools=True,
                supports_streaming=True,
                context_window=8192,
                cost_tier="free",
                enabled=True,
            ),
            "remote": LLMBackend(
                base_url="https://openrouter.ai/api/v1",
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


@pytest.fixture
def clients() -> dict[str, httpx.AsyncClient]:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no HTTP request expected during routing")

    return {
        "local": httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        "remote": httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    }


async def test_tool_turn_routes_to_tool_tier(clients):
    router = Router(make_config(remote_enabled=True), clients=clients)
    selection = router.select(tools_available=True)
    assert selection.tier == "tool"
    assert selection.backend_name == "remote"
    assert selection.reason == "tool-turn→tool tier"
    assert selection.brain._client is clients["remote"]


async def test_chat_turn_routes_to_default(clients):
    router = Router(make_config(remote_enabled=True), clients=clients)
    selection = router.select(tools_available=False)
    assert selection.tier == "default"
    assert selection.backend_name == "local"
    assert selection.reason == "chat-turn→default tier"
    assert selection.brain._client is clients["local"]


async def test_remote_disabled_falls_back_to_local(clients):
    router = Router(make_config(remote_enabled=False), clients=clients)
    selection = router.select(tools_available=True)
    assert selection.backend_name == "local"
    assert selection.reason == "tool tier disabled; local fallback"
    assert selection.brain._client is clients["local"]


async def test_tier_override_forces_tier(clients):
    router = Router(make_config(remote_enabled=True), clients=clients)
    selection = router.select(tools_available=False, tier_override="tool")
    assert selection.tier == "tool"
    assert selection.backend_name == "remote"
    assert selection.reason == "override:tool"
    assert selection.brain._client is clients["remote"]
