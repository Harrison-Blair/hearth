"""Pins the ``openrouter/free`` wire contract against ``OpenAICompatibleProvider``:
the model id reaches the wire verbatim and tool/JSON calls declare their features
(``tools`` / ``response_format``) with no special-casing of that id — this is what
lets OpenRouter's free router filter to a capable model. Stubbed httpx transport,
no network, no keys.
"""

import json

import httpx

from assistant.llm.openai_compatible_provider import GATEWAYS, OpenAICompatibleProvider


def _patch_transport(monkeypatch, handler):
    """Route the provider's AsyncClient through a MockTransport handler."""
    orig = httpx.AsyncClient

    def factory(**kwargs):
        return orig(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", factory)


def _provider() -> OpenAICompatibleProvider:
    return OpenAICompatibleProvider(
        model="openrouter/free", api_key="k", base_url=GATEWAYS["openrouter"]["base_url"]
    )


async def test_complete_sends_openrouter_free_model_verbatim(monkeypatch):
    def handler(request):
        body = json.loads(request.content)
        assert body["model"] == "openrouter/free"
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    _patch_transport(monkeypatch, handler)
    provider = _provider()
    await provider.complete("hi")
    await provider.aclose()


async def test_chat_sends_openrouter_free_model_verbatim(monkeypatch):
    def handler(request):
        body = json.loads(request.content)
        assert body["model"] == "openrouter/free"
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    _patch_transport(monkeypatch, handler)
    provider = _provider()
    await provider.chat([{"role": "user", "content": "hi"}])
    await provider.aclose()


async def test_chat_tools_sends_model_and_tools(monkeypatch):
    tools = [{"type": "function", "function": {"name": "get_weather", "parameters": {}}}]

    def handler(request):
        body = json.loads(request.content)
        assert body["model"] == "openrouter/free"
        assert body["tools"] == tools
        return httpx.Response(
            200, json={"choices": [{"message": {"content": "ok", "tool_calls": []}}]}
        )

    _patch_transport(monkeypatch, handler)
    provider = _provider()
    await provider.chat_tools([{"role": "user", "content": "hi"}], tools=tools)
    await provider.aclose()


async def test_complete_json_sets_response_format(monkeypatch):
    def handler(request):
        body = json.loads(request.content)
        assert body["model"] == "openrouter/free"
        assert body["response_format"] == {"type": "json_object"}
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

    _patch_transport(monkeypatch, handler)
    provider = _provider()
    await provider.complete("hi", json=True)
    await provider.aclose()
