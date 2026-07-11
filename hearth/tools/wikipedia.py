"""wikipedia_search: async Wikipedia REST search tool.

Config-driven (`config.tool.wikipedia_*`, flat fields — see FTHR-006 molt
evidence for the nested-vs-flat schema note). Client is injected so tests can
supply an `httpx.MockTransport` and stay hermetic.
"""
from __future__ import annotations

import httpx

from hearth.brain.base import ToolSpec

SPEC = ToolSpec(
    name="wikipedia_search",
    description="Search Wikipedia and return short summaries.",
    parameters={
        "type": "object",
        "properties": {"query": {"type": "string"}},
        "required": ["query"],
    },
    label="search",
)


async def wikipedia_search(
    query: str,
    *,
    client: httpx.AsyncClient,
    endpoint: str = "/w/rest.php/v1/search/page",
    result_count: int = 3,
    max_chars: int = 1000,
    lang: str = "en",
    timeout: float = 10.0,
) -> str:
    """Search Wikipedia and return a summary of the top `result_count` pages,
    truncated to `max_chars`."""
    url = endpoint if client.base_url else f"https://{lang}.wikipedia.org{endpoint}"
    response = await client.get(url, params={"q": query, "limit": result_count}, timeout=timeout)
    response.raise_for_status()
    body = response.json()

    summaries = [
        f"{page['title']}: {page['excerpt']}" for page in body.get("pages", [])[:result_count]
    ]
    return "\n".join(summaries)[:max_chars]
