"""Self-update skill: confirm, then restart-in-place to load code already on disk.

Confirm-then-act, modeled on ReminderSkill's bulk-cancel round: ``handle()``
never restarts directly, it only asks; ``handle_reply()`` acts on an
affirmative. Sign-off lines are canned in Calcifer's voice — deliberately not
an LLM call, since generating persona text in the moment before the process is
replaced would be fragile and slow (see FTHR-001).
"""

from __future__ import annotations

import random

from assistant.core.events import Command, Intent, SkillResult
from assistant.skills.base import Skill

_NO_ARGS = {"type": "object", "properties": {}}

_AFFIRMATIONS = ("yes", "yeah", "yep", "confirm", "do it", "go ahead", "sure")

_SIGNOFFS = (
    "Ugh, fine — dousing myself. Don't let the logs go cold.",
    "Right, going dark for a second. Try not to miss me.",
    "Fine, fine — reloading. Don't touch my wood while I'm gone.",
)


class UpdateSkill(Skill):
    name = "update"
    intents = {"update_self"}
    tool_specs = {
        "update_self": {
            "description": "Restart the assistant to load the latest code already on disk.",
            "parameters": _NO_ARGS,
        },
    }

    async def handle(self, cmd: Command, intent: Intent) -> SkillResult:
        return SkillResult(
            "I'll need to restart to pick up the update. Go ahead?",
            expects_reply=True,
        )

    async def handle_reply(self, cmd: Command) -> SkillResult:
        lowered = cmd.text.lower()
        if not any(word in lowered for word in _AFFIRMATIONS):
            return SkillResult("Okay, staying lit for now.")
        return SkillResult(random.choice(_SIGNOFFS), restart=True)
