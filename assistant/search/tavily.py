"""Web search via the Tavily API (AI-first, keyed).

Tavily is built for LLM consumption: one POST returns both ranked page results
and a synthesized `answer` string. The answer rides the same `SearchResult`
list as one more entry (source="tavily", title="answer") so it flows through
the existing merge, fencing, and neutralization in WebSearchSkill unchanged —
no new prompt channel needed.

Uses httpx (already a dependency) so no new packages are needed.
"""

from __future__ import annotations

import logging

import httpx

from assistant.search.base import SearchProvider, SearchResult, domain

log = logging.getLogger(__name__)

_DEFAULT_ENDPOINT = "https://api.tavily.com/search"


class TavilySearch(SearchProvider):
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
            "api_key": self._api_key,
            "query": query,
            "max_results": count,
            "include_answer": True,
        }
        try:
            resp = await self._client.post(self._endpoint, json=payload)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            log.error("Tavily search failed: %s", exc)
            raise

        results: list[SearchResult] = []
        for row in data.get("results") or []:
            url = row.get("url", "")
            results.append(
                SearchResult(
                    title=row.get("title", ""),
                    snippet=(row.get("content") or "")[: self._max_snippet_chars],
                    source=domain(url) or "tavily",
                    url=url,
                )
            )

        answer = data.get("answer")
        if isinstance(answer, str) and answer.strip():
            results.append(
                SearchResult(
                    title="answer",
                    snippet=answer[: self._max_snippet_chars],
                    source="tavily",
                )
            )

        return results

    async def health(self) -> bool:
        try:
            await self.search("ping", count=1)
        except Exception:
            return False
        return True
