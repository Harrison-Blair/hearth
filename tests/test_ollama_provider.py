import json

import httpx

from assistant.llm.ollama_provider import OllamaProvider


def _patch_transport(monkeypatch, handler):
    """Route the provider's AsyncClient through a MockTransport handler."""
    orig = httpx.AsyncClient

    def factory(**kwargs):
        return orig(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", factory)


async def test_complete_sends_prompt_and_strips_response(monkeypatch):
    def handler(request):
        assert request.url.path == "/api/generate"
        body = json.loads(request.content)
        assert body == {"model": "m", "prompt": "hi", "stream": False, "system": "sys"}
        return httpx.Response(200, json={"response": "  hello there  "})

    _patch_transport(monkeypatch, handler)
    assert await OllamaProvider("m").complete("hi", system="sys") == "hello there"


async def test_complete_json_flag_sets_format(monkeypatch):
    def handler(request):
        assert json.loads(request.content)["format"] == "json"
        return httpx.Response(200, json={"response": "{}"})

    _patch_transport(monkeypatch, handler)
    assert await OllamaProvider("m").complete("hi", json=True) == "{}"


async def test_health_true_when_model_present(monkeypatch):
    def handler(request):
        assert request.url.path == "/api/tags"
        return httpx.Response(200, json={"models": [{"name": "qwen2.5:3b-instruct"}]})

    _patch_transport(monkeypatch, handler)
    assert await OllamaProvider("qwen2.5:3b-instruct").health() is True


async def test_health_false_when_model_missing(monkeypatch):
    def handler(request):
        return httpx.Response(200, json={"models": [{"name": "llama3.2:3b"}]})

    _patch_transport(monkeypatch, handler)
    assert await OllamaProvider("qwen2.5:3b-instruct").health() is False


async def test_health_false_when_server_down(monkeypatch):
    def handler(request):
        raise httpx.ConnectError("connection refused")

    _patch_transport(monkeypatch, handler)
    assert await OllamaProvider("m").health() is False
