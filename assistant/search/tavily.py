"""Keyed web search via the Tavily API — an optional accelerator.

Unlike the keyless scraper, Tavily returns a direct synthesized `answer` plus
ranked result content, so live, structured facts (scores, weather) resolve
reliably. It needs an API key, so it is never the guaranteed path: when no key is
configured app.py uses the keyless `DdgsSearch` instead, and when a Tavily call
fails this provider falls back to its injected local provider. This mirrors the
repo rule that remote is an optional accelerator with a local fallback.
"""

from __future__ import annotations

import logging

import httpx

from assistant.search.base import SearchProvider, SearchResult, domain

log = logging.getLogger(__name__)


class TavilySearch(SearchProvider):
    def __init__(
        self,
        api_key: str,
        *,
        endpoint: str = "https://api.tavily.com/search",
        timeout: float = 10.0,
        max_snippet_chars: int = 500,
        fallback: SearchProvider | None = None,
    ) -> None:
        self._api_key = api_key
        self._endpoint = endpoint
        self._timeout = timeout
        self._max_snippet_chars = max_snippet_chars
        self._fallback = fallback  # local provider used when Tavily errors

    def _to_results(self, data: dict, count: int) -> list[SearchResult]:
        results: list[SearchResult] = []
        answer = (data.get("answer") or "").strip()
        if answer:
            # Tavily's synthesized answer is the highest-signal snippet; lead with it.
            results.append(
                SearchResult(
                    title="answer",
                    snippet=answer[: self._max_snippet_chars],
                    source="the web",
                )
            )
        for row in (data.get("results") or [])[:count]:
            url = row.get("url", "")
            results.append(
                SearchResult(
                    title=row.get("title", ""),
                    snippet=(row.get("content", "") or "")[: self._max_snippet_chars],
                    source=domain(url) or "the web",
                    url=url,
                )
            )
        return results

    async def search(self, query: str, *, count: int) -> list[SearchResult]:
        payload = {
            "api_key": self._api_key,
            "query": query,
            "max_results": count,
            "include_answer": True,
            "search_depth": "basic",
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(self._endpoint, json=payload)
                resp.raise_for_status()
                data = resp.json()
            return self._to_results(data, count)
        except Exception as exc:  # noqa: BLE001 - degrade to the local provider on any error
            if self._fallback is not None:
                log.warning("Tavily search failed: %s; falling back to local search", exc)
                return await self._fallback.search(query, count=count)
            log.error("Tavily search failed and no fallback configured: %s", exc)
            raise

    async def health(self) -> bool:
        try:
            await self.search("ping", count=1)
        except Exception:  # noqa: BLE001 - search() already falls back; treat error as unhealthy
            return False
        return True
