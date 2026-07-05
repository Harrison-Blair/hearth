"""Web search via the Wikipedia REST API.

Wikipedia's Action API is free, keyless, and widely accessible — no DNS blocks,
no rate limits for modest usage. Each query returns article extracts (the lead
paragraph) as plain text, which is ideal for spoken summaries.

Uses httpx (already a dependency) so no new packages are needed.
"""

from __future__ import annotations

import logging

import httpx

from assistant.search.base import SearchProvider, SearchResult

log = logging.getLogger(__name__)

_API_URL = "https://{lang}.wikipedia.org/w/api.php"


def _page_url(title: str, *, lang: str) -> str:
    return f"https://{lang}.wikipedia.org/wiki/{title.replace(' ', '_')}"


class WikipediaSearch(SearchProvider):
    def __init__(
        self,
        *,
        language: str = "en",
        result_count: int = 3,
        timeout: float = 10.0,
        max_snippet_chars: int = 500,
    ) -> None:
        self._language = language
        self._count = result_count
        self._max_snippet_chars = max_snippet_chars
        self._client = httpx.AsyncClient(timeout=timeout)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def search(self, query: str, *, count: int) -> list[SearchResult]:
        headers = {"User-Agent": "PersonalAssistant/1.0 (contact: user@example.com)"}
        params = {
            "action": "query",
            "generator": "search",
            "gsrsearch": query,
            "gsrlimit": min(count, 50),
            "prop": "extracts",
            "exintro": "1",
            "explaintext": "1",
            "format": "json",
            "origin": "*",
        }
        url = _API_URL.format(lang=self._language)
        try:
            resp = await self._client.get(url, params=params, headers=headers)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            log.error("Wikipedia search failed: %s", exc)
            raise

        pages = (data.get("query") or {}).get("pages") or {}
        pages_by_id: list[dict] = []
        for page in pages.values():
            if page.get("pageid") and page.get("title"):
                pages_by_id.append(page)
        pages_by_id.sort(key=lambda p: p.get("index", 0))

        results: list[SearchResult] = []
        for page in pages_by_id:
            title = page["title"]
            extract = (page.get("extract") or "")[: self._max_snippet_chars]
            results.append(
                SearchResult(
                    title=title,
                    snippet=extract,
                    source="wikipedia",
                    url=_page_url(title, lang=self._language),
                )
            )

        return results

    async def health(self) -> bool:
        try:
            await self.search("ping", count=1)
        except Exception:
            return False
        return True
