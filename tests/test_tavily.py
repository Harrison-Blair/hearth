import httpx

from assistant.search.base import SearchResult
from assistant.search.tavily import TavilySearch


def _patch_transport(monkeypatch, handler):
    """Route the provider's AsyncClient through a MockTransport handler."""
    orig = httpx.AsyncClient

    def factory(**kwargs):
        return orig(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", factory)


class FakeFallback:
    def __init__(self):
        self.called_with = None

    async def search(self, query, *, count):
        self.called_with = (query, count)
        return [SearchResult(title="local", snippet="from ddgs", source="ddgs")]

    async def health(self):
        return True


async def test_answer_leads_then_results(monkeypatch):
    def handler(request):
        assert request.url.host == "api.tavily.com"
        return httpx.Response(200, json={
            "answer": "USA beat Turkey 2-1.",
            "results": [{"title": "Recap", "url": "https://www.espn.com/x", "content": "Match recap."}],
        })

    _patch_transport(monkeypatch, handler)
    results = await TavilySearch("key").search("usa turkey score", count=3)
    assert results[0].snippet == "USA beat Turkey 2-1."  # synthesized answer leads
    assert results[1].title == "Recap"
    assert results[1].source == "espn.com"


async def test_falls_back_to_local_on_error(monkeypatch):
    def handler(request):
        raise httpx.ConnectError("tavily down")

    _patch_transport(monkeypatch, handler)
    fallback = FakeFallback()
    results = await TavilySearch("key", fallback=fallback).search("q", count=2)
    assert fallback.called_with == ("q", 2)
    assert results[0].source == "ddgs"


async def test_error_without_fallback_raises(monkeypatch):
    def handler(request):
        return httpx.Response(401, json={"error": "bad key"})

    _patch_transport(monkeypatch, handler)
    raised = False
    try:
        await TavilySearch("key").search("q", count=1)
    except httpx.HTTPStatusError:
        raised = True
    assert raised


async def test_snippet_truncation(monkeypatch):
    def handler(request):
        return httpx.Response(200, json={"answer": "x" * 1000, "results": []})

    _patch_transport(monkeypatch, handler)
    results = await TavilySearch("key", max_snippet_chars=50).search("q", count=1)
    assert len(results[0].snippet) == 50


async def test_health_true_on_success(monkeypatch):
    def handler(request):
        return httpx.Response(200, json={"answer": "ok", "results": []})

    _patch_transport(monkeypatch, handler)
    assert await TavilySearch("key").health() is True
