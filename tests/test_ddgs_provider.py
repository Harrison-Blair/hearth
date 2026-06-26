from assistant.search.ddgs_provider import DdgsSearch


class FakeDDGS:
    def __init__(self, text_rows=None, news_rows=None, exc=None):
        self.text_rows = text_rows or []
        self.news_rows = news_rows or []
        self.exc = exc
        self.calls = []

    def text(self, query, region=None, timelimit=None, max_results=None):
        self.calls.append(("text", query, timelimit))
        if self.exc:
            raise self.exc
        return self.text_rows[:max_results]

    def news(self, query, region=None, timelimit=None, max_results=None):
        self.calls.append(("news", query, timelimit))
        if self.exc:
            raise self.exc
        return self.news_rows[:max_results]


def _factory(text_rows=None, news_rows=None, exc=None):
    return lambda timeout: FakeDDGS(text_rows, news_rows, exc)


async def test_maps_rows_to_search_results():
    rows = [
        {"title": "T1", "href": "https://www.bbc.com/news/x", "body": "First body."},
        {"title": "T2", "href": "https://example.org/y", "body": "Second body."},
    ]
    provider = DdgsSearch(client_factory=_factory(rows))
    results = await provider.search("weather", count=2)

    assert [r.title for r in results] == ["T1", "T2"]
    assert results[0].source == "bbc.com"  # www. stripped
    assert results[1].source == "example.org"
    assert results[0].snippet == "First body."


async def test_snippet_is_truncated():
    rows = [{"title": "T", "href": "https://a.com", "body": "x" * 1000}]
    provider = DdgsSearch(max_snippet_chars=100, client_factory=_factory(rows))
    results = await provider.search("q", count=1)
    assert len(results[0].snippet) == 100


async def test_no_results_returns_empty_list():
    provider = DdgsSearch(client_factory=_factory([]))
    assert await provider.search("q", count=3) == []


async def test_missing_domain_falls_back_to_the_web():
    rows = [{"title": "T", "href": "", "body": "b"}]
    provider = DdgsSearch(client_factory=_factory(rows))
    results = await provider.search("q", count=1)
    assert results[0].source == "the web"


async def test_health_false_when_client_raises():
    provider = DdgsSearch(client_factory=_factory(exc=RuntimeError("blocked")))
    assert await provider.health() is False


async def test_health_true_on_success():
    provider = DdgsSearch(client_factory=_factory([{"title": "t", "href": "https://a.com", "body": "b"}]))
    assert await provider.health() is True


async def test_news_results_lead_and_use_named_source():
    news = [{"title": "Live", "url": "https://espn.com/g", "body": "Latest.", "source": "ESPN"}]
    text = [{"title": "Old", "href": "https://wiki.org/g", "body": "Background."}]
    provider = DdgsSearch(client_factory=_factory(text_rows=text, news_rows=news))
    results = await provider.search("score", count=3)
    # News is freshest, so it leads; its explicit 'source' is used verbatim.
    assert results[0].title == "Live"
    assert results[0].source == "ESPN"
    assert results[1].title == "Old"


async def test_dedupes_same_url_across_backends():
    shared = "https://espn.com/g"
    news = [{"title": "N", "url": shared, "body": "n", "source": "ESPN"}]
    text = [{"title": "T", "href": shared, "body": "t"}]
    provider = DdgsSearch(client_factory=_factory(text_rows=text, news_rows=news))
    results = await provider.search("q", count=3)
    assert len(results) == 1
    assert results[0].title == "N"  # news copy wins


async def test_timelimit_is_passed_to_backends():
    captured = {}

    class Recorder(FakeDDGS):
        def text(self, query, region=None, timelimit=None, max_results=None):
            captured["timelimit"] = timelimit
            return []

    provider = DdgsSearch(timelimit="w", client_factory=lambda timeout: Recorder())
    await provider.search("q", count=1)
    assert captured["timelimit"] == "w"
