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
        assert body == {
            "model": "m",
            "prompt": "hi",
            "stream": False,
            "options": {"num_ctx": 8192},
            "system": "sys",
        }
        return httpx.Response(200, json={"response": "  hello there  "})

    _patch_transport(monkeypatch, handler)
    assert await OllamaProvider("m").complete("hi", system="sys") == "hello there"


async def test_complete_json_flag_sets_format_and_disables_thinking(monkeypatch):
    def handler(request):
        body = json.loads(request.content)
        assert body["format"] == "json"
        assert body["think"] is False
        return httpx.Response(200, json={"response": "{}"})

    _patch_transport(monkeypatch, handler)
    assert await OllamaProvider("m").complete("hi", json=True) == "{}"


async def test_complete_non_json_omits_think(monkeypatch):
    def handler(request):
        assert "think" not in json.loads(request.content)
        return httpx.Response(200, json={"response": "ok"})

    _patch_transport(monkeypatch, handler)
    assert await OllamaProvider("m").complete("hi") == "ok"


async def test_complete_logs_labeled_trace(monkeypatch, caplog):
    def handler(request):
        return httpx.Response(200, json={"response": "hi there"})

    _patch_transport(monkeypatch, handler)
    with caplog.at_level("INFO", logger="assistant.llm.ollama_provider"):
        await OllamaProvider("m").complete("a question", system="be brief", label="answer")
    messages = [r.getMessage() for r in caplog.records]
    assert "[answer] prompt: a question" in messages
    assert "[answer] system: be brief" in messages
    assert "[answer] response: hi there" in messages


async def test_complete_unlabeled_uses_llm_tag(monkeypatch, caplog):
    def handler(request):
        return httpx.Response(200, json={"response": "ok"})

    _patch_transport(monkeypatch, handler)
    with caplog.at_level("INFO", logger="assistant.llm.ollama_provider"):
        await OllamaProvider("m").complete("hi")
    messages = [r.getMessage() for r in caplog.records]
    assert "[llm] prompt: hi" in messages
    assert "[llm] response: ok" in messages
    # No system was passed -> no system line.
    assert not any("system:" in m for m in messages)


async def test_chat_sends_messages_and_strips_content(monkeypatch):
    def handler(request):
        assert request.url.path == "/api/chat"
        body = json.loads(request.content)
        assert body == {
            "model": "m",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": False,
            "think": False,
            "options": {"num_ctx": 8192},
        }
        return httpx.Response(200, json={"message": {"content": "  hello there  "}})

    _patch_transport(monkeypatch, handler)
    msgs = [{"role": "user", "content": "hi"}]
    assert await OllamaProvider("m").chat(msgs) == "hello there"


async def test_chat_prepends_system_message(monkeypatch):
    def handler(request):
        body = json.loads(request.content)
        assert body["messages"] == [
            {"role": "system", "content": "be brief"},
            {"role": "user", "content": "hi"},
        ]
        return httpx.Response(200, json={"message": {"content": "ok"}})

    _patch_transport(monkeypatch, handler)
    await OllamaProvider("m").chat([{"role": "user", "content": "hi"}], system="be brief")


async def test_chat_omits_system_when_none(monkeypatch):
    def handler(request):
        body = json.loads(request.content)
        assert all(m["role"] != "system" for m in body["messages"])
        return httpx.Response(200, json={"message": {"content": "ok"}})

    _patch_transport(monkeypatch, handler)
    await OllamaProvider("m").chat([{"role": "user", "content": "hi"}])


async def test_chat_tools_sends_tools_and_parses_calls(monkeypatch):
    tools = [{"type": "function", "function": {"name": "echo"}}]

    def handler(request):
        assert request.url.path == "/api/chat"
        body = json.loads(request.content)
        assert body["tools"] == tools
        assert body["stream"] is False
        return httpx.Response(
            200,
            json={
                "message": {
                    "content": "",
                    "tool_calls": [{"function": {"name": "echo", "arguments": {"text": "hi"}}}],
                }
            },
        )

    _patch_transport(monkeypatch, handler)
    resp = await OllamaProvider("m").chat_tools([{"role": "user", "content": "hi"}], tools=tools)
    assert resp.content == ""
    assert len(resp.tool_calls) == 1
    assert resp.tool_calls[0].name == "echo"
    assert resp.tool_calls[0].arguments == {"text": "hi"}


async def test_chat_tools_parses_string_arguments(monkeypatch):
    def handler(request):
        return httpx.Response(
            200,
            json={
                "message": {
                    "tool_calls": [{"function": {"name": "echo", "arguments": '{"text": "hi"}'}}]
                }
            },
        )

    _patch_transport(monkeypatch, handler)
    resp = await OllamaProvider("m").chat_tools([{"role": "user", "content": "hi"}])
    assert resp.tool_calls[0].arguments == {"text": "hi"}


async def test_chat_tools_content_only_when_no_calls(monkeypatch):
    def handler(request):
        assert "tools" not in json.loads(request.content)  # omitted when none given
        return httpx.Response(200, json={"message": {"content": "  hello there  "}})

    _patch_transport(monkeypatch, handler)
    resp = await OllamaProvider("m").chat_tools([{"role": "user", "content": "hi"}])
    assert resp.content == "hello there"
    assert resp.tool_calls == []


async def test_num_ctx_threaded_into_options(monkeypatch):
    def handler(request):
        assert json.loads(request.content)["options"] == {"num_ctx": 4096}
        return httpx.Response(200, json={"message": {"content": "ok"}})

    _patch_transport(monkeypatch, handler)
    provider = OllamaProvider("m", num_ctx=4096)
    await provider.chat_tools([{"role": "user", "content": "hi"}])


async def test_think_flag_reaches_chat_payloads(monkeypatch):
    seen = []

    def handler(request):
        seen.append(json.loads(request.content)["think"])
        return httpx.Response(200, json={"message": {"content": "ok"}})

    _patch_transport(monkeypatch, handler)
    provider = OllamaProvider("m", think=True)
    await provider.chat([{"role": "user", "content": "hi"}])
    await provider.chat_tools([{"role": "user", "content": "hi"}])
    assert seen == [True, True]


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
