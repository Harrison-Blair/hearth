"""Guards + retry for ``OpenAICompatibleProvider._post``.

A transient 200 with a truncated/empty body used to escape as a bare
``KeyError``/``IndexError``/``JSONDecodeError`` and trip the fallback on
something that may simply have been a retryable gateway hiccup. These cover the
new ``LLMResponseError`` shape, the retry policy (retry 429/5xx/transport +
retryable malformed bodies; never retry 4xx-auth), and ``max_retries``.
"""

import json

import httpx
import pytest

from assistant.llm.openai_compatible_provider import LLMResponseError, OpenAICompatibleProvider


def _patch_transport(monkeypatch, handler):
    orig = httpx.AsyncClient

    def factory(**kwargs):
        return orig(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", factory)


def _ok(content="ok"):
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})


async def test_empty_choices_raises_retryable(monkeypatch):
    def handler(request):
        return httpx.Response(200, json={"choices": []})

    _patch_transport(monkeypatch, handler)
    provider = OpenAICompatibleProvider("m", "k", max_retries=0)
    with pytest.raises(LLMResponseError) as exc_info:
        await provider.complete("hi")
    assert exc_info.value.retryable is True
    await provider.aclose()


async def test_missing_message_raises_retryable(monkeypatch):
    def handler(request):
        return httpx.Response(200, json={"choices": [{}]})

    _patch_transport(monkeypatch, handler)
    provider = OpenAICompatibleProvider("m", "k", max_retries=0)
    with pytest.raises(LLMResponseError) as exc_info:
        await provider.complete("hi")
    assert exc_info.value.retryable is True
    await provider.aclose()


async def test_non_json_body_raises_retryable(monkeypatch):
    def handler(request):
        return httpx.Response(200, text="<html>gateway lost the stream</html>")

    _patch_transport(monkeypatch, handler)
    provider = OpenAICompatibleProvider("m", "k", max_retries=0)
    with pytest.raises(LLMResponseError) as exc_info:
        await provider.complete("hi")
    assert exc_info.value.retryable is True
    await provider.aclose()


async def test_non_dict_body_raises_retryable(monkeypatch):
    def handler(request):
        return httpx.Response(200, json=[1, 2, 3])

    _patch_transport(monkeypatch, handler)
    provider = OpenAICompatibleProvider("m", "k", max_retries=0)
    with pytest.raises(LLMResponseError) as exc_info:
        await provider.complete("hi")
    assert exc_info.value.retryable is True
    await provider.aclose()


async def test_retries_on_429_then_succeeds(monkeypatch):
    calls = [0]

    def handler(request):
        calls[0] += 1
        if calls[0] == 1:
            return httpx.Response(429, text="rate limited")
        return _ok("after retry")

    _patch_transport(monkeypatch, handler)
    provider = OpenAICompatibleProvider("m", "k", max_retries=2, retry_backoff_s=0.0)
    assert await provider.complete("hi") == "after retry"
    assert calls[0] == 2  # one failure, one success
    await provider.aclose()


async def test_retries_on_503_then_succeeds(monkeypatch):
    calls = [0]

    def handler(request):
        calls[0] += 1
        if calls[0] == 1:
            return httpx.Response(503, text="unavailable")
        return _ok()

    _patch_transport(monkeypatch, handler)
    provider = OpenAICompatibleProvider("m", "k", max_retries=2, retry_backoff_s=0.0)
    assert await provider.complete("hi") == "ok"
    assert calls[0] == 2
    await provider.aclose()


async def test_retries_on_transport_error_then_succeeds(monkeypatch):
    calls = [0]

    def handler(request):
        calls[0] += 1
        if calls[0] == 1:
            raise httpx.ConnectError("connection reset")
        return _ok()

    _patch_transport(monkeypatch, handler)
    provider = OpenAICompatibleProvider("m", "k", max_retries=2, retry_backoff_s=0.0)
    assert await provider.complete("hi") == "ok"
    assert calls[0] == 2
    await provider.aclose()


async def test_retries_on_malformed_body_then_succeeds(monkeypatch):
    calls = [0]

    def handler(request):
        calls[0] += 1
        if calls[0] == 1:
            return httpx.Response(200, json={"choices": []})  # truncated/garbage
        return _ok("recovered")

    _patch_transport(monkeypatch, handler)
    provider = OpenAICompatibleProvider("m", "k", max_retries=2, retry_backoff_s=0.0)
    assert await provider.complete("hi") == "recovered"
    assert calls[0] == 2
    await provider.aclose()


async def test_no_retry_on_401(monkeypatch):
    calls = [0]

    def handler(request):
        calls[0] += 1
        return httpx.Response(401, text="unauthorized")

    _patch_transport(monkeypatch, handler)
    provider = OpenAICompatibleProvider("m", "k", max_retries=2, retry_backoff_s=0.0)
    with pytest.raises(httpx.HTTPStatusError) as exc_info:
        await provider.complete("hi")
    assert exc_info.value.response.status_code == 401
    assert calls[0] == 1  # never retried
    await provider.aclose()


async def test_no_retry_on_403(monkeypatch):
    calls = [0]

    def handler(request):
        calls[0] += 1
        return httpx.Response(403, text="forbidden")

    _patch_transport(monkeypatch, handler)
    provider = OpenAICompatibleProvider("m", "k", max_retries=2, retry_backoff_s=0.0)
    with pytest.raises(httpx.HTTPStatusError):
        await provider.complete("hi")
    assert calls[0] == 1
    await provider.aclose()


async def test_no_retry_on_400(monkeypatch):
    calls = [0]

    def handler(request):
        calls[0] += 1
        return httpx.Response(400, text="bad request")

    _patch_transport(monkeypatch, handler)
    provider = OpenAICompatibleProvider("m", "k", max_retries=2, retry_backoff_s=0.0)
    with pytest.raises(httpx.HTTPStatusError):
        await provider.complete("hi")
    assert calls[0] == 1
    await provider.aclose()


async def test_persistent_429_exhausts_retries_and_raises(monkeypatch):
    calls = [0]

    def handler(request):
        calls[0] += 1
        return httpx.Response(429, text="rate limited")

    _patch_transport(monkeypatch, handler)
    provider = OpenAICompatibleProvider("m", "k", max_retries=2, retry_backoff_s=0.0)
    with pytest.raises(httpx.HTTPStatusError):
        await provider.complete("hi")
    assert calls[0] == 3  # initial + 2 retries
    await provider.aclose()


async def test_persistent_malformed_exhausts_retries_and_raises(monkeypatch):
    calls = [0]

    def handler(request):
        calls[0] += 1
        return httpx.Response(200, json={"choices": []})

    _patch_transport(monkeypatch, handler)
    provider = OpenAICompatibleProvider("m", "k", max_retries=2, retry_backoff_s=0.0)
    with pytest.raises(LLMResponseError) as exc_info:
        await provider.complete("hi")
    assert exc_info.value.retryable is True
    assert calls[0] == 3
    await provider.aclose()


async def test_max_retries_zero_is_one_attempt(monkeypatch):
    calls = [0]

    def handler(request):
        calls[0] += 1
        return httpx.Response(503, text="down")

    _patch_transport(monkeypatch, handler)
    provider = OpenAICompatibleProvider("m", "k", max_retries=0, retry_backoff_s=0.0)
    with pytest.raises(httpx.HTTPStatusError):
        await provider.complete("hi")
    assert calls[0] == 1
    await provider.aclose()


async def test_guard_does_not_fire_on_null_content(monkeypatch):
    # A well-formed 200 carrying null content is a valid response (empty string),
    # not a malformed body — must not trip the guard.
    def handler(request):
        return httpx.Response(200, json={"choices": [{"message": {"content": None}}]})

    _patch_transport(monkeypatch, handler)
    provider = OpenAICompatibleProvider("m", "k", max_retries=0)
    assert await provider.complete("hi") == ""
    await provider.aclose()


async def test_chat_tools_validates_choices(monkeypatch):
    def handler(request):
        return httpx.Response(200, json={"choices": []})

    _patch_transport(monkeypatch, handler)
    provider = OpenAICompatibleProvider("m", "k", max_retries=0)
    with pytest.raises(LLMResponseError):
        await provider.chat_tools([{"role": "user", "content": "hi"}])
    await provider.aclose()


async def test_retry_payload_unchanged_across_attempts(monkeypatch):
    # The same payload must be re-sent on each retry (no mutation drift).
    seen = []

    def handler(request):
        body = json.loads(request.content)
        seen.append(body)
        return httpx.Response(503, text="down")

    _patch_transport(monkeypatch, handler)
    provider = OpenAICompatibleProvider("m", "k", max_retries=1, retry_backoff_s=0.0)
    with pytest.raises(httpx.HTTPStatusError):
        await provider.complete("hi", system="be brief")
    assert len(seen) == 2
    assert seen[0] == seen[1]
    assert seen[0]["messages"][0]["role"] == "system"
    await provider.aclose()
