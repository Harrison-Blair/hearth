import httpx

from assistant.search.wikipedia import WikipediaSearch


def _patch_transport(monkeypatch, handler):
    orig = httpx.AsyncClient

    def factory(**kwargs):
        return orig(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", factory)


async def test_maps_results_with_extracts(monkeypatch):
    def handler(request):
        assert "action=query" in str(request.url)
        return httpx.Response(200, json={
            "batchcomplete": "",
            "query": {
                "pages": {
                    "1": {
                        "pageid": 1,
                        "ns": 0,
                        "title": "Python (programming language)",
                        "index": 1,
                        "extract": "Python is a high-level, general-purpose programming language.",
                    },
                    "2": {
                        "pageid": 2,
                        "ns": 0,
                        "title": "Monty Python",
                        "index": 2,
                        "extract": "Monty Python were a British comedy group.",
                    },
                }
            },
        })

    _patch_transport(monkeypatch, handler)
    results = await WikipediaSearch().search("python", count=2)

    assert len(results) == 2
    assert results[0].title == "Python (programming language)"
    assert results[0].snippet == "Python is a high-level, general-purpose programming language."
    assert results[0].source == "wikipedia"
    assert results[0].url == "https://en.wikipedia.org/wiki/Python_(programming_language)"
    assert results[1].title == "Monty Python"


async def test_results_ordered_by_index(monkeypatch):
    def handler(request):
        return httpx.Response(200, json={
            "batchcomplete": "",
            "query": {
                "pages": {
                    "2": {"pageid": 2, "ns": 0, "title": "B", "index": 2, "extract": "Second."},
                    "1": {"pageid": 1, "ns": 0, "title": "A", "index": 1, "extract": "First."},
                }
            },
        })

    _patch_transport(monkeypatch, handler)
    results = await WikipediaSearch().search("q", count=2)
    assert [r.title for r in results] == ["A", "B"]


async def test_snippet_is_truncated(monkeypatch):
    def handler(request):
        return httpx.Response(200, json={
            "batchcomplete": "",
            "query": {
                "pages": {
                    "1": {"pageid": 1, "ns": 0, "title": "T", "index": 1, "extract": "x" * 1000},
                }
            },
        })

    _patch_transport(monkeypatch, handler)
    results = await WikipediaSearch(max_snippet_chars=100).search("q", count=1)
    assert len(results[0].snippet) == 100


async def test_no_results_returns_empty_list(monkeypatch):
    def handler(request):
        return httpx.Response(200, json={
            "batchcomplete": "",
            "query": {"pages": {}},
        })

    _patch_transport(monkeypatch, handler)
    assert await WikipediaSearch().search("q", count=3) == []


async def test_missing_query_key_returns_empty(monkeypatch):
    def handler(request):
        return httpx.Response(200, json={"batchcomplete": ""})

    _patch_transport(monkeypatch, handler)
    assert await WikipediaSearch().search("q", count=3) == []


async def test_health_false_when_api_raises(monkeypatch):
    def handler(request):
        raise httpx.ConnectError("dns failure")

    _patch_transport(monkeypatch, handler)
    assert await WikipediaSearch().health() is False


async def test_health_true_on_success(monkeypatch):
    def handler(request):
        return httpx.Response(200, json={
            "batchcomplete": "",
            "query": {
                "pages": {
                    "1": {"pageid": 1, "ns": 0, "title": "Ping", "index": 1, "extract": "Ok."},
                }
            },
        })

    _patch_transport(monkeypatch, handler)
    assert await WikipediaSearch().health() is True


async def test_uses_custom_language(monkeypatch):
    def handler(request):
        assert "de.wikipedia.org" in str(request.url)
        return httpx.Response(200, json={
            "batchcomplete": "",
            "query": {
                "pages": {
                    "1": {"pageid": 1, "ns": 0, "title": "Python", "index": 1, "extract": "Python ist."},
                }
            },
        })

    _patch_transport(monkeypatch, handler)
    results = await WikipediaSearch(language="de").search("python", count=1)
    assert results[0].url == "https://de.wikipedia.org/wiki/Python"
    assert results[0].snippet == "Python ist."


async def test_gsrlimit_respects_count(monkeypatch):
    captured = {}

    class Handler:
        async def handle(self, request):
            captured["gsrlimit"] = request.url.params.get("gsrlimit")
            return httpx.Response(200, json={
                "batchcomplete": "",
                "query": {"pages": {}},
            })

    _patch_transport(monkeypatch, Handler().handle)
    await WikipediaSearch().search("q", count=5)
    assert captured["gsrlimit"] == "5"
