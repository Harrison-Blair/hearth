"""RemoteBackend (OpenRouter) sends the Bearer key and parses completions, hermetically."""
from __future__ import annotations

import httpx

from hearth.brain.base import Message
from hearth.brain.remote import RemoteBackend
from hearth.config import LLMBackend


async def test_remote_backend_auth_and_parse(canned_completion, monkeypatch):
    monkeypatch.setenv("HEARTH_LLM__OPENROUTER_API_KEY", "sk-test-123")
    backend_config = LLMBackend(
        base_url="https://openrouter.ai/api/v1",
        model="openrouter/free",
        api_key_env="HEARTH_LLM__OPENROUTER_API_KEY",
        supports_tools=True,
        supports_streaming=True,
        context_window=8192,
        cost_tier="free",
        enabled=True,
    )
    seen_requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_requests.append(request)
        return httpx.Response(200, json=canned_completion(text="hi from remote"))

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url=backend_config.base_url
    )
    backend = RemoteBackend(backend_config, client=client, name="remote", tier="tool")

    result = await backend.complete([Message(role="user", content="hi")], tools=None)

    assert result.text == "hi from remote"
    assert result.backend == "remote"
    assert result.tier == "tool"
    assert len(seen_requests) == 1
    assert seen_requests[0].headers["authorization"] == "Bearer sk-test-123"

    await client.aclose()
