"""Self-update skill: confirm, then restart-in-place to load code already on disk.

Confirm-then-act, modeled on ReminderSkill's bulk-cancel round: ``handle()``
never restarts directly, it only asks; ``handle_reply()`` acts on an
affirmative. The sign-off is a canned() registry lookup — deliberately not an
LLM call, since generating persona text in the moment before the process is
replaced would be fragile and slow (see FTHR-001).
"""

from __future__ import annotations

import random

from assistant.core.events import Command, Intent, SkillResult
from assistant.core.persona import canned
from assistant.skills.base import Skill

_NO_ARGS = {"type": "object", "properties": {}}

_AFFIRMATIONS = ("yes", "yeah", "yep", "confirm", "do it", "go ahead", "sure")


class UpdateSkill(Skill):
    name = "update"
    intents = {"update_self"}
    tool_specs = {
        "update_self": {
            "description": "Restart the assistant to load the latest code already on disk.",
            "parameters": _NO_ARGS,
        },
    }

    def __init__(
        self, persona_enabled: bool = False, rng: random.Random | None = None
    ) -> None:
        self.persona_enabled = persona_enabled
        self._rng = rng

    async def handle(self, cmd: Command, intent: Intent) -> SkillResult:
        return SkillResult(
            "I'll need to restart to pick up the update. Go ahead?",
            expects_reply=True,
        )

    async def handle_reply(self, cmd: Command) -> SkillResult:
        lowered = cmd.text.lower()
        if not any(word in lowered for word in _AFFIRMATIONS):
            return SkillResult("Okay, staying lit for now.")
        signoff = canned("update_signoff", enabled=self.persona_enabled, rng=self._rng)
        return SkillResult(signoff, restart=True, voiced=True)
