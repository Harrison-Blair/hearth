"""BrainError crash-hardening for _OpenAICompatBackend.complete(), via LocalBackend."""
from __future__ import annotations

import httpx
import pytest

from hearth.brain.base import Message
from hearth.brain.errors import BrainError
from hearth.brain.local import LocalBackend


async def test_http_error_raises_brain_error(llm_config):
    backend_config = llm_config.backends["local"]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="internal server error")

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url=backend_config.base_url
    )
    backend = LocalBackend(backend_config, client=client, name="local", tier="default")

    with pytest.raises(BrainError) as excinfo:
        await backend.complete([Message(role="user", content="hi")], tools=None)

    # A status error came from a reachable backend: distinct, still curated reason.
    assert excinfo.value.reason == "backend error"
    assert "500" in excinfo.value.detail

    await client.aclose()


async def test_malformed_body_raises_brain_error(llm_config):
    backend_config = llm_config.backends["local"]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"nope": "no choices here"})

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url=backend_config.base_url
    )
    backend = LocalBackend(backend_config, client=client, name="local", tier="default")

    with pytest.raises(BrainError) as excinfo:
        await backend.complete([Message(role="user", content="hi")], tools=None)

    assert excinfo.value.reason == "unreadable response"

    await client.aclose()


async def test_bad_tool_arguments_raises_brain_error(llm_config, canned_completion):
    backend_config = llm_config.backends["local"]
    body = canned_completion(
        text=None,
        tool_calls=[
            {
                "id": "call_1",
                "type": "function",
                "function": {"name": "lookup", "arguments": "{not valid json"},
            }
        ],
        finish_reason="tool_calls",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=body)

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url=backend_config.base_url
    )
    backend = LocalBackend(backend_config, client=client, name="local", tier="default")

    with pytest.raises(BrainError) as excinfo:
        await backend.complete([Message(role="user", content="hi")], tools=None)

    assert excinfo.value.reason == "unreadable response"

    await client.aclose()


async def test_brain_error_never_leaks_api_key(monkeypatch):
    from hearth.brain.remote import RemoteBackend
    from hearth.config import LLMBackend

    monkeypatch.setenv("HEARTH_LLM__OPENROUTER_API_KEY", "sk-super-secret-123")
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

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="internal server error")

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url=backend_config.base_url
    )
    backend = RemoteBackend(backend_config, client=client, name="remote", tier="tool")

    with pytest.raises(BrainError) as excinfo:
        await backend.complete([Message(role="user", content="hi")], tools=None)

    assert "sk-super-secret-123" not in excinfo.value.reason
    assert "sk-super-secret-123" not in excinfo.value.detail
    assert "sk-super-secret-123" not in str(excinfo.value)

    await client.aclose()


async def test_malformed_tool_call_structure_raises_brain_error(llm_config, canned_completion):
    """A tool call missing "function" (or "id") is curated to "unreadable
    response", not a raw KeyError out of complete()."""
    backend_config = llm_config.backends["local"]
    body = canned_completion(
        text=None,
        tool_calls=[{"id": "call_1", "type": "function"}],  # no "function" key
        finish_reason="tool_calls",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=body)

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url=backend_config.base_url
    )
    backend = LocalBackend(backend_config, client=client, name="local", tier="default")

    with pytest.raises(BrainError) as excinfo:
        await backend.complete([Message(role="user", content="hi")], tools=None)

    assert excinfo.value.reason == "unreadable response"

    await client.aclose()
