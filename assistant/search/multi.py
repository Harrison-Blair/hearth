"""Fan-out composite: query every configured provider, merge the results.

Providers run concurrently; a failing one (DuckDuckGo rate limit, network) is
logged and skipped so any healthy provider still answers. Results are
interleaved round-robin — the top hit from each provider first — so the
downstream LLM sees every backend's best result and judges between them via the
per-result source attribution.
"""

from __future__ import annotations

import asyncio
import logging

from assistant.search.base import SearchProvider, SearchResult

log = logging.getLogger(__name__)


class MultiSearch(SearchProvider):
    def __init__(self, providers: list[SearchProvider], *, max_results: int = 5) -> None:
        self._providers = providers
        self._max_results = max_results

    async def search(self, query: str, *, count: int) -> list[SearchResult]:
        outcomes = await asyncio.gather(
            *(p.search(query, count=count) for p in self._providers),
            return_exceptions=True,
        )
        lists: list[list[SearchResult]] = []
        last_exc: BaseException | None = None
        for provider, outcome in zip(self._providers, outcomes):
            if isinstance(outcome, BaseException):
                log.warning("Provider %s failed: %s", type(provider).__name__, outcome)
                last_exc = outcome
            else:
                lists.append(outcome)
        if not lists and last_exc is not None:
            raise last_exc
        return self._merge(lists)

    def _merge(self, lists: list[list[SearchResult]]) -> list[SearchResult]:
        merged: list[SearchResult] = []
        seen: set[str] = set()
        for rank in range(max((len(rs) for rs in lists), default=0)):
            for rs in lists:
                if rank >= len(rs):
                    continue
                result = rs[rank]
                key = result.url.rstrip("/").lower() or f"{result.source}:{result.title}"
                if key in seen:
                    continue
                seen.add(key)
                merged.append(result)
                if len(merged) == self._max_results:
                    return merged
        return merged

    async def health(self) -> bool:
        checks = await asyncio.gather(
            *(p.health() for p in self._providers), return_exceptions=True
        )
        return any(c is True for c in checks)

    async def aclose(self) -> None:
        for provider in self._providers:
            await provider.aclose()
