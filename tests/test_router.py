"""Router.select: deterministic, config-driven tier routing -- always the
default/local tier unless explicitly overridden -- plus brain_available()
gating (FTHR-009: the `tools_available` signal that used to promote a turn
to the tool tier is gone; that's now `consult_brain`'s job via
`tier_override="tool"`)."""
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


async def test_select_default_ignores_tools_available(clients):
    """`select()` with no override always resolves the default/local tier --
    there is no `tools_available` signal anymore that can promote it to
    remote (that's what `consult_brain` + `tier_override` are for now)."""
    router = Router(make_config(remote_enabled=True), clients=clients)
    selection = router.select()
    assert selection.tier == "default"
    assert selection.backend_name == "local"
    assert selection.reason == "chat-turn→default tier"
    assert selection.brain._client is clients["local"]


async def test_select_tier_override_reaches_remote(clients):
    router = Router(make_config(remote_enabled=True), clients=clients)
    selection = router.select(tier_override="tool")
    assert selection.tier == "tool"
    assert selection.backend_name == "remote"
    assert selection.reason == "override:tool"
    assert selection.brain._client is clients["remote"]


async def test_brain_available_true_when_remote_enabled(clients):
    router = Router(make_config(remote_enabled=True), clients=clients)
    assert router.brain_available() is True


async def test_brain_available_false_when_remote_disabled(clients):
    router = Router(make_config(remote_enabled=False), clients=clients)
    assert router.brain_available() is False
