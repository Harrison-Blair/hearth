"""Keyless web search via the `ddgs` DuckDuckGo scraper.

`ddgs` returns real ranked results (including recent news) with no API key, which
fits the offline-first, no-cloud-account ethos. It is an unofficial scrape, so it
can rate-limit or break on a page change; the skill treats any failure as a
graceful degrade, never a crash (see WebSearchSkill).

To favour fresh information, each query hits both the `news` backend (date-stamped,
recent) and the `text` backend, biased to a recent time window, then merges them
(news first). Note: scraped snippets are static page descriptions, so this is good
for recent *reporting* but cannot surface live, in-progress figures (e.g. a score
mid-game) — that needs the keyed Tavily accelerator.

The library is synchronous, so calls run in worker threads to honour the async
SearchProvider contract.
"""

from __future__ import annotations

import asyncio
import logging

from assistant.search.base import SearchProvider, SearchResult, domain

log = logging.getLogger(__name__)


def _default_client(timeout: float):
    from ddgs import DDGS  # imported lazily so the suite runs without the `search` extra

    return DDGS(timeout=timeout)


class DdgsSearch(SearchProvider):
    def __init__(
        self,
        *,
        result_count: int = 3,
        timeout: float = 10.0,
        region: str = "wt-wt",
        timelimit: str = "d",  # ddgs recency window: d/w/m/y; bias toward fresh results
        max_snippet_chars: int = 500,
        client_factory=_default_client,
    ) -> None:
        self._count = result_count
        self._timeout = timeout
        self._region = region
        self._timelimit = timelimit
        self._max_snippet_chars = max_snippet_chars
        self._client_factory = client_factory  # injectable so tests need no network

    def _query(self, kind: str, query: str, count: int) -> list[dict]:
        # A client per query (not pooled): search() runs the two _query calls in
        # separate worker threads concurrently, and ddgs.DDGS is not guaranteed
        # thread-safe, so each thread gets its own isolated client.
        client = self._client_factory(self._timeout)
        fn = client.news if kind == "news" else client.text
        return fn(query, region=self._region, timelimit=self._timelimit, max_results=count)

    def _to_result(self, row: dict) -> SearchResult:
        # News rows carry 'url' + a named 'source'; text rows carry 'href' only.
        url = row.get("url") or row.get("href", "")
        return SearchResult(
            title=row.get("title", ""),
            snippet=(row.get("body", "") or "")[: self._max_snippet_chars],
            source=row.get("source") or domain(url) or "the web",
            url=url,
        )

    def _merge(self, news: list[dict], text: list[dict], count: int) -> list[dict]:
        seen: set[str] = set()
        out: list[dict] = []
        for row in [*(news or []), *(text or [])]:  # news first: it is the freshest
            # Dedupe on url, falling back to title so urlless rows (scrape variance)
            # don't all slip through and crowd out distinct results.
            key = (row.get("url") or row.get("href") or row.get("title") or "").strip().lower()
            if key and key in seen:
                continue
            seen.add(key)
            out.append(row)
            if len(out) >= count:
                break
        return out

    async def search(self, query: str, *, count: int) -> list[SearchResult]:
        # Run both backends concurrently so freshness costs no extra wall-clock.
        news, text = await asyncio.gather(
            asyncio.to_thread(self._query, "news", query, count),
            asyncio.to_thread(self._query, "text", query, count),
        )
        return [self._to_result(r) for r in self._merge(news, text, count)]

    async def health(self) -> bool:
        try:
            await asyncio.to_thread(self._query, "text", "ping", 1)
        except Exception as exc:  # noqa: BLE001 - any scrape/network error means unreachable
            log.warning("ddgs health check failed: %s", exc)
            return False
        return True
