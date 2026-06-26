"""Intent router interface.

The concrete two-tier router is implemented: ``KeyphraseRouter`` (cheap substring
match) and ``ClassifierRouter`` (LLM picks one label, degrading to the keyphrase
tier offline) both subclass this ABC. ``Intent`` itself lives in core.events so
skills can import it freely.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from assistant.core.events import Intent


class IntentRouter(ABC):
    @abstractmethod
    async def route(self, text: str) -> Intent:
        """Map raw transcript text to an Intent."""
