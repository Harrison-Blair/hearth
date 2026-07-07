"""Web search via the Exa API (AI-first, keyed, neural/semantic index).

Exa is built for "find me things like..." style queries. Its `/search` endpoint
can return per-result `highlights` — short, relevance-ranked excerpts — which map
cleanly into `SearchResult.snippet` without wasting the `max_snippet_chars` cap on
a truncated page dump. When highlights are absent, fall back to a truncated
`text`/`summary` field.

Uses httpx (already a dependency) so no new packages are needed.
"""

from __future__ import annotations

import logging

import httpx

from assistant.search.base import SearchProvider, SearchResult, domain

log = logging.getLogger(__name__)

_DEFAULT_ENDPOINT = "https://api.exa.ai/search"


class ExaSearch(SearchProvider):
    def __init__(
        self,
        *,
        api_key: str,
        endpoint: str = _DEFAULT_ENDPOINT,
        timeout: float = 10.0,
        max_snippet_chars: int = 500,
    ) -> None:
        self._api_key = api_key
        self._endpoint = endpoint
        self._max_snippet_chars = max_snippet_chars
        self._client = httpx.AsyncClient(timeout=timeout)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def search(self, query: str, *, count: int) -> list[SearchResult]:
        payload = {
            "query": query,
            "numResults": count,
            "contents": {"highlights": True},
        }
        headers = {"x-api-key": self._api_key}
        try:
            resp = await self._client.post(self._endpoint, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            log.error("Exa search failed: %s", exc)
            raise

        results: list[SearchResult] = []
        for row in data.get("results") or []:
            url = row.get("url", "")
            highlights = row.get("highlights") or []
            if highlights:
                snippet = " ".join(highlights)
            else:
                snippet = row.get("text") or row.get("summary") or ""
            results.append(
                SearchResult(
                    title=row.get("title", ""),
                    snippet=snippet[: self._max_snippet_chars],
                    source=domain(url) or "exa",
                    url=url,
                )
            )
        return results

    async def health(self) -> bool:
        try:
            await self.search("ping", count=1)
        except Exception:
            return False
        return True
