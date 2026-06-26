"""Web search provider interface.

A capability behind an ABC, like llm/ and tts/: the pipeline-facing skill depends
only on SearchProvider, never a concrete backend, so a keyed API (Tavily/Brave)
can replace the keyless scraper with a one-line change in app.py.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from urllib.parse import urlparse


def domain(url: str) -> str:
    """Bare host of a URL for spoken attribution, e.g. 'bbc.com'. '' if none."""
    netloc = urlparse(url).netloc
    return netloc[4:] if netloc.startswith("www.") else netloc


@dataclass
class SearchResult:
    """One web result. Flows only provider -> skill, so it lives here, not in
    core/events.py (it is not a cross-stage pipeline record)."""

    title: str
    snippet: str
    source: str  # spoken attribution name, e.g. "bbc.com" (URL domain)
    url: str = ""


class SearchProvider(ABC):
    @abstractmethod
    async def search(self, query: str, *, count: int) -> list[SearchResult]:
        """Return up to `count` results; [] if nothing found."""

    @abstractmethod
    async def health(self) -> bool:
        """Return True if the backend is reachable."""

    async def aclose(self) -> None:
        """Release any held resources (e.g. an HTTP client). No-op by default."""
