"""Intent router interface.

The concrete two-tier router (keyphrase matcher then LLM classifier) lands in
Phase 3. ``Intent`` itself lives in core.events so skills can import it freely.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from assistant.core.events import Intent


class IntentRouter(ABC):
    @abstractmethod
    async def route(self, text: str) -> Intent:
        """Map raw transcript text to an Intent."""
