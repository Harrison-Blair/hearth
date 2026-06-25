"""Skill plugin interface and registry.

A new capability = one Skill subclass + one register() call. The router maps
Intent.type -> Skill via the registry and never hard-codes skill names.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from assistant.core.events import Command, Intent, SkillResult


class Skill(ABC):
    name: str
    intents: set[str]

    @abstractmethod
    async def handle(self, cmd: Command, intent: Intent) -> SkillResult:
        """Handle a routed command and return spoken result + data."""


class SkillRegistry:
    def __init__(self) -> None:
        self._by_intent: dict[str, Skill] = {}
        self._default: Skill | None = None

    def register(self, skill: Skill, *, default: bool = False) -> None:
        for intent in skill.intents:
            self._by_intent[intent] = skill
        if default:
            self._default = skill

    def get(self, intent_type: str) -> Skill | None:
        return self._by_intent.get(intent_type, self._default)
