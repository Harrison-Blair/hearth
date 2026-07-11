"""LocalBackend parses an OpenAI-compatible completion, hermetically via MockTransport."""
from __future__ import annotations

import httpx

from hearth.brain.base import Message
from hearth.brain.local import LocalBackend


async def test_local_backend_parses_completion(llm_config, canned_completion):
    backend_config = llm_config.backends["local"]
    body = canned_completion(text="hi there")
    seen_requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_requests.append(request)
        return httpx.Response(200, json=body)

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url=backend_config.base_url
    )
    backend = LocalBackend(backend_config, client=client, name="local", tier="default")

    result = await backend.complete([Message(role="user", content="hi")], tools=None)

    assert result.text == "hi there"
    assert result.tool_calls == []
    assert result.finish_reason == "stop"
    assert result.backend == "local"
    assert result.tier == "default"
    assert len(seen_requests) == 1
    assert seen_requests[0].url.path.endswith("/chat/completions")

    await client.aclose()


async def test_local_backend_still_parses(llm_config, canned_completion):
    """After the FTHR-004 base-class refactor, LocalBackend still parses tool calls."""
    backend_config = llm_config.backends["local"]
    body = canned_completion(
        text=None,
        tool_calls=[
            {
                "id": "call_1",
                "type": "function",
                "function": {"name": "lookup", "arguments": '{"query": "fire"}'},
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

    result = await backend.complete([Message(role="user", content="hi")], tools=None)

    assert result.text is None
    assert result.finish_reason == "tool_calls"
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].name == "lookup"
    assert result.tool_calls[0].arguments == {"query": "fire"}

    await client.aclose()
