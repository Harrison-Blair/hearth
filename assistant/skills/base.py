"""Skill plugin interface and registry.

A new capability = one Skill subclass + one register() call. The router maps
Intent.type -> Skill via the registry and never hard-codes skill names.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from assistant.core.events import Command, Intent, SkillResult

# Fallback tool schema for an intent a skill declares no explicit spec for: a
# single free-text argument carrying the user's request verbatim.
_DEFAULT_PARAMS = {
    "type": "object",
    "properties": {
        "text": {"type": "string", "description": "the user's full request, verbatim"}
    },
    "required": ["text"],
}


class Skill(ABC):
    name: str
    intents: set[str]
    # Tool metadata the orchestrator exposes to the model, per intent:
    # {intent: {"description": str, "parameters": <JSON schema>}}. An intent with
    # no entry here still gets a generic single-text-argument tool so it routes.
    tool_specs: dict[str, dict] = {}

    @abstractmethod
    async def handle(self, cmd: Command, intent: Intent) -> SkillResult:
        """Handle a routed command and return spoken result + data."""

    def tools(self) -> list[dict]:
        """OpenAI-style function schemas the model may call, one per declared
        intent. The tool name IS the intent, so the registry dispatches a call by
        name with no extra mapping. Override to contribute no tools (e.g. the
        general fallback, whose reach is a direct answer, not a tool)."""
        specs: list[dict] = []
        for intent in sorted(self.intents):
            meta = self.tool_specs.get(intent, {})
            specs.append({
                "type": "function",
                "function": {
                    "name": intent,
                    "description": meta.get("description", ""),
                    "parameters": meta.get("parameters", _DEFAULT_PARAMS),
                },
            })
        return specs

    async def handle_reply(self, cmd: Command) -> SkillResult:
        """Handle the follow-up reply to a result that set ``expects_reply``.

        Only skills that ask for a reply need to override this; the default is a
        generic failure so a stray reply never silently succeeds."""
        return SkillResult(speech="Sorry, I wasn't expecting a reply.", success=False)


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

    @property
    def intents(self) -> set[str]:
        """The intents explicitly registered by a skill (excludes the default
        fallback's catch-all reach)."""
        return set(self._by_intent)

    def tool_schemas(self) -> list[dict]:
        """Every registered skill's tool schemas, for the orchestrator's tool loop.
        The default fallback contributes none (a direct model answer stands in for
        its 'general' reach), so its intent is never offered as a callable tool."""
        schemas: list[dict] = []
        seen: list[Skill] = []
        for skill in self._by_intent.values():
            if skill in seen:
                continue
            seen.append(skill)
            schemas.extend(skill.tools())
        return schemas
