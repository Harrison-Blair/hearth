"""LocalBackend parses an OpenAI-compatible completion, hermetically via MockTransport."""
from __future__ import annotations

import httpx
import pytest

from hearth.brain.base import Message
from hearth.brain.errors import BrainError
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


async def test_retries_transient_connection_error(llm_config, canned_completion):
    """A transient connection error is retried up to max_retries; the call
    succeeds once the backend recovers."""
    backend_config = llm_config.backends["local"]
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        if attempts["n"] <= 2:
            raise httpx.ConnectError("connection refused", request=request)
        return httpx.Response(200, json=canned_completion(text="recovered"))

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url=backend_config.base_url
    )
    backend = LocalBackend(backend_config, client=client, name="local", tier="default", max_retries=2)

    result = await backend.complete([Message(role="user", content="hi")], tools=None)

    assert result.text == "recovered"
    assert attempts["n"] == 3  # 2 failures + 1 success

    await client.aclose()


async def test_no_retry_exhausts_and_raises(llm_config):
    """max_retries=0 makes a single attempt, then surfaces backend unreachable."""
    backend_config = llm_config.backends["local"]
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        raise httpx.ConnectError("connection refused", request=request)

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url=backend_config.base_url
    )
    backend = LocalBackend(backend_config, client=client, name="local", tier="default", max_retries=0)

    with pytest.raises(BrainError) as excinfo:
        await backend.complete([Message(role="user", content="hi")], tools=None)

    assert excinfo.value.reason == "backend unreachable"
    assert attempts["n"] == 1  # no retries

    await client.aclose()


async def test_timeout_is_not_retried(llm_config):
    """A read timeout means the model is already too slow -- retrying just
    burns the turn budget, so it must NOT be retried even with max_retries."""
    backend_config = llm_config.backends["local"]
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        raise httpx.ReadTimeout("timed out", request=request)

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url=backend_config.base_url
    )
    backend = LocalBackend(backend_config, client=client, name="local", tier="default", max_retries=2)

    with pytest.raises(BrainError) as excinfo:
        await backend.complete([Message(role="user", content="hi")], tools=None)

    assert excinfo.value.reason == "backend unreachable"
    assert attempts["n"] == 1  # timeout: single attempt, no retry

    await client.aclose()
