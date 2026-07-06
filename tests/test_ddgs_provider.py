import pytest

from assistant.search import ddgs_provider
from assistant.search.ddgs_provider import DdgsSearch


class FakeDDGS:
    """Stands in for ddgs.DDGS: records constructor/text args, returns rows."""

    rows: list[dict] = []
    exc: Exception | None = None
    calls: list[dict] = []

    def __init__(self, **kwargs):
        FakeDDGS.calls.append({"init": kwargs})

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def text(self, query, **kwargs):
        FakeDDGS.calls.append({"query": query, **kwargs})
        if FakeDDGS.exc:
            raise FakeDDGS.exc
        return FakeDDGS.rows


@pytest.fixture(autouse=True)
def fake_ddgs(monkeypatch):
    FakeDDGS.rows = []
    FakeDDGS.exc = None
    FakeDDGS.calls = []
    monkeypatch.setattr(ddgs_provider, "DDGS", FakeDDGS)
    return FakeDDGS


async def test_maps_rows_to_results_with_domain_source():
    FakeDDGS.rows = [
        {"title": "Cat lifespan", "href": "https://www.vet.org/cats", "body": "Cats live 15 years."}
    ]
    results = await DdgsSearch().search("cat lifespan", count=3)
    assert len(results) == 1
    r = results[0]
    assert r.title == "Cat lifespan"
    assert r.snippet == "Cats live 15 years."
    assert r.source == "vet.org"  # www. stripped by domain()
    assert r.url == "https://www.vet.org/cats"


async def test_snippet_truncated_to_max_chars():
    FakeDDGS.rows = [{"title": "t", "href": "https://a.com", "body": "x" * 1000}]
    results = await DdgsSearch(max_snippet_chars=100).search("q", count=1)
    assert len(results[0].snippet) == 100


async def test_region_timeout_and_count_passed_through():
    FakeDDGS.rows = []
    await DdgsSearch(region="de-de", timeout=5.0).search("q", count=7)
    init, text = FakeDDGS.calls
    assert init == {"init": {"timeout": 5.0}}
    assert text == {"query": "q", "region": "de-de", "max_results": 7}


async def test_backend_error_propagates():
    FakeDDGS.exc = RuntimeError("rate limited")
    with pytest.raises(RuntimeError):
        await DdgsSearch().search("q", count=1)


async def test_health_true_on_success_false_on_error():
    FakeDDGS.rows = [{"title": "t", "href": "https://a.com", "body": "b"}]
    assert await DdgsSearch().health() is True
    FakeDDGS.exc = RuntimeError("down")
    assert await DdgsSearch().health() is False
