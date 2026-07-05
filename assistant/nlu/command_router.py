"""First-tier intent router for explicit tool invocation.

When a transcript starts with the configured keyphrase (e.g. "tool"), the
next token is parsed as a tool/intent name and the remainder as arguments,
bypassing the LLM classifier and keyphrase substring matcher.
"""

from __future__ import annotations

from assistant.core.events import Intent
from assistant.nlu.router import IntentRouter
from assistant.skills.base import SkillRegistry


class CommandEntryRouter(IntentRouter):
    def __init__(
        self,
        keyphrase: str,
        registry: SkillRegistry,
        next_router: IntentRouter,
        aliases: dict[str, str] | None = None,
    ) -> None:
        self._keyphrase = keyphrase.lower().strip()
        self._registry = registry
        self._next = next_router
        self._aliases = aliases or {}

    async def route(self, text: str) -> Intent:
        lowered = text.lower().strip()
        if not (lowered == self._keyphrase or lowered.startswith(self._keyphrase + " ")):
            return await self._next.route(text)

        rest = text[len(self._keyphrase) :].strip()
        if not rest:
            return await self._next.route(text)

        parts = rest.split(maxsplit=1)
        tool_name = parts[0].lower()
        tool_args = parts[1] if len(parts) > 1 else ""

        intent_type = self._aliases.get(tool_name, tool_name)
        if intent_type not in self._registry.intents:
            return await self._next.route(text)

        return Intent(type=intent_type, raw_text=tool_args)
