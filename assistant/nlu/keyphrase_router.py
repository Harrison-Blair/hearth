"""Fast keyphrase intent router.

Tier one of the planned two-tier router: a cheap substring match against
registered keyphrases, falling back to a default intent. The LLM-classifier
tier lands once there are enough skills for keyphrases to be ambiguous.
"""

from __future__ import annotations

from assistant.core.events import Intent
from assistant.nlu.router import IntentRouter


class KeyphraseRouter(IntentRouter):
    def __init__(self, default_intent: str = "general") -> None:
        self._default = default_intent
        self._keyphrases: list[tuple[str, str]] = []  # (phrase, intent)

    def add(self, intent: str, *phrases: str) -> None:
        for phrase in phrases:
            self._keyphrases.append((phrase.lower(), intent))

    @property
    def intents(self) -> set[str]:
        """The intents that have at least one registered keyphrase."""
        return {intent for _, intent in self._keyphrases}

    async def route(self, text: str) -> Intent:
        lowered = text.lower()
        for phrase, intent in self._keyphrases:
            if phrase in lowered:
                return Intent(type=intent, raw_text=text)
        return Intent(type=self._default, raw_text=text)
