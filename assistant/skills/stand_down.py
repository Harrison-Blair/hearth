"""Stand-down skill: stop listening (and all proactive speech) on request.

Engages the shared StandDown state for a spoken duration, or indefinitely when
none is given — the pause then ends when the timer expires or the user taps
Resume on the monitor TUI. Voice can't resume (wake detection is off), so the
indefinite confirmation says how to wake it.
"""

from __future__ import annotations

from assistant.core.events import Command, Intent, SkillResult
from assistant.core.standdown import StandDown
from assistant.nlu.timespec import humanize, parse_duration
from assistant.skills.base import Skill


class StandDownSkill(Skill):
    name = "stand_down"
    intents = {"stand_down"}
    tool_specs = {
        "stand_down": {
            "description": (
                "Stop listening and stay silent, optionally for a duration; the user "
                "resumes from the screen or the timer expires."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "duration": {
                        "type": "string",
                        "description": "e.g. '30 minutes'; omit to stand down indefinitely",
                    }
                },
            },
        },
    }

    def __init__(self, standdown: StandDown) -> None:
        self._standdown = standdown

    async def handle(self, cmd: Command, intent: Intent) -> SkillResult:
        seconds = parse_duration(intent.slots.get("duration") or cmd.text)
        self._standdown.engage(seconds)
        if seconds is None:
            return SkillResult("Okay, standing down until you wake me from the screen.")
        return SkillResult(
            f"Okay, standing down for {humanize(seconds).removeprefix('in ')}."
        )
