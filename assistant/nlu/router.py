"""Intent router interface.

Used by the orchestrator's LLM-free fast path: ``CommandEntryRouter`` (explicit
"tool X" invocation) and ``KeyphraseRouter`` (cheap substring match) both subclass
this ABC and chain together. ``Intent`` itself lives in core.events so skills can
import it freely.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from assistant.core.events import Intent


class IntentRouter(ABC):
    @abstractmethod
    async def route(self, text: str) -> Intent:
        """Map raw transcript text to an Intent."""
