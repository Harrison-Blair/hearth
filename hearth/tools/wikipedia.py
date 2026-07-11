"""wikipedia_search: async Wikipedia REST search tool.

Config-driven (`config.tool.wikipedia_*`, flat fields — see FTHR-006 molt
evidence for the nested-vs-flat schema note). Client is injected so tests can
supply an `httpx.MockTransport` and stay hermetic.
"""
from __future__ import annotations

import httpx

from hearth import __version__
from hearth.brain.base import ToolSpec

# Wikimedia's REST API rejects requests without a descriptive User-Agent (403),
# per https://foundation.wikimedia.org/wiki/Policy:User-Agent_policy.
_USER_AGENT = f"hearth-personal-assistant/{__version__} (offline voice assistant)"

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
    # An unset httpx base_url is `URL('')` -- truthy but empty, so guard on the
    # string form. Prod wires this client with no base_url, so the tool builds
    # the absolute URL; tests inject a MockTransport base_url and pass `endpoint`
    # relative to it.
    url = endpoint if str(client.base_url) else f"https://{lang}.wikipedia.org{endpoint}"
    response = await client.get(
        url,
        params={"q": query, "limit": result_count},
        headers={"User-Agent": _USER_AGENT},
        timeout=timeout,
    )
    response.raise_for_status()
    body = response.json()

    summaries = [
        f"{page['title']}: {page['excerpt']}" for page in body.get("pages", [])[:result_count]
    ]
    return "\n".join(summaries)[:max_chars]
