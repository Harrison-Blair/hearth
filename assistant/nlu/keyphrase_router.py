"""Fast keyphrase intent router.

The orchestrator's LLM-free fast path: a cheap substring match against registered
keyphrases for common commands, falling back to a default intent. A default (no
match) hands the turn to the orchestrator's tool-calling loop.
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
