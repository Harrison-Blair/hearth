import pytest

from assistant.search.base import SearchResult
from assistant.search.multi import MultiSearch


class FakeProvider:
    def __init__(self, results=None, exc=None, healthy=True):
        self.results = results or []
        self.exc = exc
        self.healthy = healthy
        self.closed = False
        self.queries = []

    async def search(self, query, *, count):
        self.queries.append((query, count))
        if self.exc:
            raise self.exc
        return self.results

    async def health(self):
        return self.healthy

    async def aclose(self):
        self.closed = True


def _r(url, source="s"):
    return SearchResult(title="t", snippet="text", source=source, url=url)


async def test_results_interleaved_round_robin():
    a = FakeProvider([_r("https://a.com/1"), _r("https://a.com/2")])
    b = FakeProvider([_r("https://b.com/1"), _r("https://b.com/2")])
    results = await MultiSearch([a, b]).search("q", count=3)
    assert [r.url for r in results] == [
        "https://a.com/1", "https://b.com/1", "https://a.com/2", "https://b.com/2",
    ]
    assert a.queries == b.queries == [("q", 3)]


async def test_duplicate_urls_deduped():
    a = FakeProvider([_r("https://same.com/x")])
    b = FakeProvider([_r("https://same.com/x/")])  # trailing slash normalized away
    results = await MultiSearch([a, b]).search("q", count=3)
    assert len(results) == 1


async def test_merged_results_capped_at_max():
    a = FakeProvider([_r(f"https://a.com/{i}") for i in range(4)])
    b = FakeProvider([_r(f"https://b.com/{i}") for i in range(4)])
    results = await MultiSearch([a, b], max_results=3).search("q", count=4)
    assert len(results) == 3


async def test_one_failing_provider_is_skipped():
    a = FakeProvider(exc=RuntimeError("rate limited"))
    b = FakeProvider([_r("https://b.com/1")])
    results = await MultiSearch([a, b]).search("q", count=3)
    assert [r.url for r in results] == ["https://b.com/1"]


async def test_all_providers_failing_reraises():
    a = FakeProvider(exc=RuntimeError("down"))
    b = FakeProvider(exc=RuntimeError("also down"))
    with pytest.raises(RuntimeError):
        await MultiSearch([a, b]).search("q", count=3)


async def test_all_empty_returns_empty():
    assert await MultiSearch([FakeProvider(), FakeProvider()]).search("q", count=3) == []


async def test_health_true_if_any_child_healthy():
    assert await MultiSearch([FakeProvider(healthy=False), FakeProvider()]).health() is True
    assert await MultiSearch([FakeProvider(healthy=False)]).health() is False


async def test_aclose_closes_all_children():
    a, b = FakeProvider(), FakeProvider()
    await MultiSearch([a, b]).aclose()
    assert a.closed and b.closed
