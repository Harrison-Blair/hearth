"""Web search via DuckDuckGo (the `ddgs` package).

Keyless real-web results. The ddgs client is synchronous, so each search runs in
a worker thread (the repo pattern for blocking calls, e.g. STT/TTS). DuckDuckGo
rate-limits scrapers, so callers should expect occasional failures — MultiSearch
absorbs them and merges whatever the other providers return.
"""

from __future__ import annotations

import asyncio
import logging

from ddgs import DDGS

from assistant.search.base import SearchProvider, SearchResult, domain

log = logging.getLogger(__name__)


class DdgsSearch(SearchProvider):
    def __init__(
        self,
        *,
        region: str = "us-en",
        timeout: float = 10.0,
        max_snippet_chars: int = 500,
    ) -> None:
        self._region = region
        self._timeout = timeout
        self._max_snippet_chars = max_snippet_chars

    async def search(self, query: str, *, count: int) -> list[SearchResult]:
        try:
            rows = await asyncio.to_thread(self._search_sync, query, count)
        except Exception as exc:
            log.error("DuckDuckGo search failed: %s", exc)
            raise
        results: list[SearchResult] = []
        for row in rows:
            url = row.get("href") or ""
            results.append(
                SearchResult(
                    title=row.get("title") or "",
                    snippet=(row.get("body") or "")[: self._max_snippet_chars],
                    source=domain(url),
                    url=url,
                )
            )
        return results

    def _search_sync(self, query: str, count: int) -> list[dict]:
        # A fresh client per call: DDGS holds no reusable connection worth pooling,
        # and per-call construction keeps this object thread-safe.
        with DDGS(timeout=self._timeout) as client:
            return client.text(query, region=self._region, max_results=count)

    async def health(self) -> bool:
        try:
            await self.search("ping", count=1)
        except Exception:
            return False
        return True
