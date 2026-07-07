import json

import httpx

from assistant.llm.openai_compatible_provider import OpenAICompatibleProvider


def _patch_transport(monkeypatch, handler):
    """Route the provider's AsyncClient through a MockTransport handler."""
    orig = httpx.AsyncClient

    def factory(**kwargs):
        return orig(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", factory)


async def test_complete_sends_prompt_and_strips_response(monkeypatch):
    def handler(request):
        assert request.url.path == "/zen/v1/chat/completions"
        body = json.loads(request.content)
        assert body == {
            "model": "deepseek-v4-flash-free",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": False,
        }
        return httpx.Response(
            200, json={"choices": [{"message": {"content": "  hello there  "}}]}
        )

    _patch_transport(monkeypatch, handler)
    provider = OpenAICompatibleProvider("deepseek-v4-flash-free", "k")
    assert await provider.complete("hi") == "hello there"
    await provider.aclose()


async def test_blank_api_key_omits_auth_header():
    # Regression: a blank key built "Authorization: Bearer " (trailing space), which
    # httpx rejects as an illegal header value at construction/send time.
    provider = OpenAICompatibleProvider("m", "")
    assert "authorization" not in provider._client.headers
    await provider.aclose()


async def test_api_key_sets_bearer_header():
    provider = OpenAICompatibleProvider("m", "k")
    assert provider._client.headers["authorization"] == "Bearer k"
    await provider.aclose()


async def test_complete_prepends_system_message(monkeypatch):
    def handler(request):
        body = json.loads(request.content)
        assert body["messages"] == [
            {"role": "system", "content": "be brief"},
            {"role": "user", "content": "hi"},
        ]
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    _patch_transport(monkeypatch, handler)
    provider = OpenAICompatibleProvider("m", "k")
    await provider.complete("hi", system="be brief")
    await provider.aclose()


async def test_complete_json_flag_sets_response_format(monkeypatch):
    def handler(request):
        body = json.loads(request.content)
        assert body["response_format"] == {"type": "json_object"}
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

    _patch_transport(monkeypatch, handler)
    provider = OpenAICompatibleProvider("m", "k")
    assert await provider.complete("hi", json=True) == "{}"
    await provider.aclose()


async def test_complete_omits_response_format_when_not_json(monkeypatch):
    def handler(request):
        assert "response_format" not in json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    _patch_transport(monkeypatch, handler)
    provider = OpenAICompatibleProvider("m", "k")
    await provider.complete("hi")
    await provider.aclose()


async def test_complete_handles_null_content(monkeypatch):
    def handler(request):
        return httpx.Response(200, json={"choices": [{"message": {"content": None}}]})

    _patch_transport(monkeypatch, handler)
    provider = OpenAICompatibleProvider("m", "k")
    assert await provider.complete("hi") == ""
    await provider.aclose()


async def test_chat_sends_messages_and_strips_content(monkeypatch):
    def handler(request):
        assert request.url.path == "/zen/v1/chat/completions"
        body = json.loads(request.content)
        assert body == {
            "model": "m",
            "messages": [{"role": "user", "content": "hi"}],
            "stream": False,
        }
        return httpx.Response(
            200, json={"choices": [{"message": {"content": "  hello there  "}}]}
        )

    _patch_transport(monkeypatch, handler)
    provider = OpenAICompatibleProvider("m", "k")
    msgs = [{"role": "user", "content": "hi"}]
    assert await provider.chat(msgs) == "hello there"
    await provider.aclose()


async def test_chat_prepends_system_message(monkeypatch):
    def handler(request):
        body = json.loads(request.content)
        assert body["messages"] == [
            {"role": "system", "content": "be brief"},
            {"role": "user", "content": "hi"},
        ]
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    _patch_transport(monkeypatch, handler)
    provider = OpenAICompatibleProvider("m", "k")
    await provider.chat([{"role": "user", "content": "hi"}], system="be brief")
    await provider.aclose()


async def test_chat_tools_sends_tools_and_parses_calls(monkeypatch):
    tools = [{"type": "function", "function": {"name": "echo"}}]

    def handler(request):
        body = json.loads(request.content)
        assert body["tools"] == tools
        assert body["stream"] is False
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": "",
                            "tool_calls": [
                                {"function": {"name": "echo", "arguments": {"text": "hi"}}}
                            ],
                        }
                    }
                ]
            },
        )

    _patch_transport(monkeypatch, handler)
    provider = OpenAICompatibleProvider("m", "k")
    resp = await provider.chat_tools([{"role": "user", "content": "hi"}], tools=tools)
    assert resp.content == ""
    assert len(resp.tool_calls) == 1
    assert resp.tool_calls[0].name == "echo"
    assert resp.tool_calls[0].arguments == {"text": "hi"}
    await provider.aclose()


async def test_chat_tools_parses_string_arguments(monkeypatch):
    def handler(request):
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "tool_calls": [
                                {"function": {"name": "echo", "arguments": '{"text": "hi"}'}}
                            ]
                        }
                    }
                ]
            },
        )

    _patch_transport(monkeypatch, handler)
    provider = OpenAICompatibleProvider("m", "k")
    resp = await provider.chat_tools([{"role": "user", "content": "hi"}])
    assert resp.tool_calls[0].arguments == {"text": "hi"}
    await provider.aclose()


async def test_chat_tools_content_only_when_no_calls(monkeypatch):
    def handler(request):
        assert "tools" not in json.loads(request.content)
        return httpx.Response(
            200, json={"choices": [{"message": {"content": "  hello there  "}}]}
        )

    _patch_transport(monkeypatch, handler)
    provider = OpenAICompatibleProvider("m", "k")
    resp = await provider.chat_tools([{"role": "user", "content": "hi"}])
    assert resp.content == "hello there"
    assert resp.tool_calls == []
    await provider.aclose()


async def test_chat_tools_handles_null_content_with_tool_calls(monkeypatch):
    def handler(request):
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": None,
                            "tool_calls": [
                                {"function": {"name": "echo", "arguments": {}}}
                            ],
                        }
                    }
                ]
            },
        )

    _patch_transport(monkeypatch, handler)
    provider = OpenAICompatibleProvider("m", "k")
    resp = await provider.chat_tools([{"role": "user", "content": "hi"}])
    assert resp.content == ""
    assert len(resp.tool_calls) == 1
    await provider.aclose()


async def test_auth_header_sent(monkeypatch):
    def handler(request):
        assert request.headers["Authorization"] == "Bearer secret-key"
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    _patch_transport(monkeypatch, handler)
    provider = OpenAICompatibleProvider("m", "secret-key")
    await provider.chat([{"role": "user", "content": "hi"}])
    await provider.aclose()


async def test_base_url_routed(monkeypatch):
    def handler(request):
        assert request.url.host == "example.com"
        assert request.url.path == "/v1/chat/completions"
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    _patch_transport(monkeypatch, handler)
    provider = OpenAICompatibleProvider("m", "k", base_url="https://example.com/v1")
    await provider.chat([{"role": "user", "content": "hi"}])
    await provider.aclose()


async def test_trace_record_carries_full_content(monkeypatch, caplog):
    long_prompt = "p" * 500
    long_response = "r" * 500

    def handler(request):
        return httpx.Response(
            200, json={"choices": [{"message": {"content": long_response}}]}
        )

    _patch_transport(monkeypatch, handler)
    provider = OpenAICompatibleProvider("m", "k")
    with caplog.at_level("INFO", logger="assistant.llm.openai_compatible_provider"):
        await provider.complete(long_prompt, system="be brief", label="agent")
    record = next(r for r in caplog.records if getattr(r, "data", None))
    assert record.getMessage() == f"[agent] response: {'r' * 200}…"
    assert record.data["kind"] == "llm.complete"
    assert record.data["prompt"] == long_prompt
    assert record.data["response"] == long_response
    assert record.data["model"] == "m"
    assert record.data["label"] == "agent"
    assert isinstance(record.data["latency_ms"], int)
    await provider.aclose()


async def test_chat_tools_trace_record(monkeypatch, caplog):
    tools = [{"type": "function", "function": {"name": "echo"}}]

    def handler(request):
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": "",
                            "tool_calls": [
                                {"function": {"name": "echo", "arguments": {"text": "hi"}}}
                            ],
                        }
                    }
                ]
            },
        )

    _patch_transport(monkeypatch, handler)
    provider = OpenAICompatibleProvider("m", "k")
    with caplog.at_level("INFO", logger="assistant.llm.openai_compatible_provider"):
        await provider.chat_tools([{"role": "user", "content": "hi"}], tools=tools)
    record = next(r for r in caplog.records if getattr(r, "data", None))
    assert record.data["kind"] == "llm.chat_tools"
    assert record.data["tools"] == ["echo"]
    assert record.data["tool_calls"] == [{"name": "echo", "arguments": {"text": "hi"}}]
    assert isinstance(record.data["latency_ms"], int)
    await provider.aclose()


async def test_health_true_when_reachable(monkeypatch):
    def handler(request):
        assert request.url.path == "/zen/v1/models"
        return httpx.Response(200, json={"data": [{"id": "deepseek-v4-flash-free"}]})

    _patch_transport(monkeypatch, handler)
    provider = OpenAICompatibleProvider("deepseek-v4-flash-free", "k")
    assert await provider.health() is True
    await provider.aclose()


async def test_health_false_when_server_down(monkeypatch):
    def handler(request):
        raise httpx.ConnectError("connection refused")

    _patch_transport(monkeypatch, handler)
    provider = OpenAICompatibleProvider("m", "k")
    assert await provider.health() is False
    await provider.aclose()


async def test_health_false_on_http_error(monkeypatch):
    def handler(request):
        return httpx.Response(401, text="unauthorized")

    _patch_transport(monkeypatch, handler)
    provider = OpenAICompatibleProvider("m", "k")
    assert await provider.health() is False
    await provider.aclose()


async def test_extra_headers_merge_onto_auth(monkeypatch):
    def handler(request):
        assert request.headers["Authorization"] == "Bearer k"
        assert request.headers["X-Foo"] == "bar"
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    _patch_transport(monkeypatch, handler)
    provider = OpenAICompatibleProvider("m", "k", extra_headers={"X-Foo": "bar"})
    await provider.chat([{"role": "user", "content": "hi"}])
    await provider.aclose()


async def test_extra_headers_none_leaves_auth_untouched(monkeypatch):
    def handler(request):
        assert request.headers["Authorization"] == "Bearer k"
        assert "X-Foo" not in request.headers
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    _patch_transport(monkeypatch, handler)
    provider = OpenAICompatibleProvider("m", "k", extra_headers=None)
    await provider.chat([{"role": "user", "content": "hi"}])
    await provider.aclose()


async def test_extra_headers_empty_leaves_auth_untouched(monkeypatch):
    def handler(request):
        assert request.headers["Authorization"] == "Bearer k"
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    _patch_transport(monkeypatch, handler)
    provider = OpenAICompatibleProvider("m", "k", extra_headers={})
    await provider.chat([{"role": "user", "content": "hi"}])
    await provider.aclose()


async def test_generic_model_sent_verbatim(monkeypatch):
    def handler(request):
        body = json.loads(request.content)
        assert body["model"] == "meta-llama/llama-3.1-70b-instruct"
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    _patch_transport(monkeypatch, handler)
    provider = OpenAICompatibleProvider("meta-llama/llama-3.1-70b-instruct", "k")
    await provider.complete("hi")
    await provider.aclose()


async def test_generic_chat_tools_declares_tools_feature(monkeypatch):
    tools = [{"type": "function", "function": {"name": "echo"}}]

    def handler(request):
        body = json.loads(request.content)
        assert "tools" in body
        assert body["tools"] == tools
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    _patch_transport(monkeypatch, handler)
    provider = OpenAICompatibleProvider("some/model", "k")
    await provider.chat_tools([{"role": "user", "content": "hi"}], tools=tools)
    await provider.aclose()


async def test_generic_complete_json_declares_response_format_feature(monkeypatch):
    def handler(request):
        body = json.loads(request.content)
        assert body["response_format"] == {"type": "json_object"}
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

    _patch_transport(monkeypatch, handler)
    provider = OpenAICompatibleProvider("some/model", "k")
    await provider.complete("hi", json=True)
    await provider.aclose()
