"""hearth.tools.wikipedia: hermetic tests via httpx.MockTransport."""
from __future__ import annotations

import httpx

from hearth.tools.wikipedia import wikipedia_search


CANNED_BODY = {
    "pages": [
        {
            "title": "Python (programming language)",
            "excerpt": "Python is a high-level, general-purpose programming language.",
        },
        {
            "title": "Python (genus)",
            "excerpt": "Pythons are a group of nonvenomous snakes found in Africa, Asia.",
        },
        {
            "title": "Monty Python",
            "excerpt": "Monty Python were a British surreal comedy group.",
        },
    ]
}


def _make_client(handler, base_url: str = "https://en.wikipedia.org") -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url=base_url)


async def test_wikipedia_search_parses():
    seen_request = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen_request["url"] = str(request.url)
        return httpx.Response(200, json=CANNED_BODY)

    client = _make_client(handler)
    result = await wikipedia_search(
        "python",
        client=client,
        endpoint="/w/rest.php/v1/search/page",
        result_count=3,
        max_chars=1000,
    )

    assert "Python (programming language)" in result
    assert "Python is a high-level" in result
    assert "python" in seen_request["url"]
    assert "search/page" in seen_request["url"]

    await client.aclose()


async def test_wikipedia_search_respects_result_count():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=CANNED_BODY)

    client = _make_client(handler)
    result = await wikipedia_search(
        "python",
        client=client,
        endpoint="/w/rest.php/v1/search/page",
        result_count=1,
        max_chars=1000,
    )

    assert "Python (programming language)" in result
    assert "Monty Python" not in result

    await client.aclose()


async def test_wikipedia_search_respects_max_chars():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=CANNED_BODY)

    client = _make_client(handler)
    result = await wikipedia_search(
        "python",
        client=client,
        endpoint="/w/rest.php/v1/search/page",
        result_count=3,
        max_chars=20,
    )

    assert len(result) <= 20

    await client.aclose()
