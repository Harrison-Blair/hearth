"""Clock skill: speak the current local time or date.

Pure request/response — no scheduling or proactive audio. Exposes the
``time`` / ``date`` tool intents.
"""

from __future__ import annotations

from datetime import datetime
from typing import Callable

from assistant.core.events import Command, Intent, SkillResult
from assistant.skills.base import Skill


def _ordinal(n: int) -> str:
    """1 -> '1st', 2 -> '2nd', 11 -> '11th', 21 -> '21st'."""
    if 11 <= n % 100 <= 13:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


_NO_ARGS = {"type": "object", "properties": {}}


class ClockSkill(Skill):
    name = "clock"
    intents = {"time", "date"}
    tool_specs = {
        "time": {"description": "Get the current clock time.", "parameters": _NO_ARGS},
        "date": {
            "description": (
                "Get today's calendar date or day of the week. Only for asking what "
                "the date/day is — not for events, schedules, or news happening today."
            ),
            "parameters": _NO_ARGS,
        },
    }

    def __init__(self, now: Callable[[], datetime] = datetime.now) -> None:
        self._now = now  # injectable for deterministic tests

    async def handle(self, cmd: Command, intent: Intent) -> SkillResult:
        now = self._now()
        if intent.type == "date":
            speech = f"Today is {now:%A, %B} {_ordinal(now.day)}."
            data = {"date": now.date().isoformat(), "weekday": f"{now:%A}"}
        else:
            speech = f"It's {now:%-I:%M %p}."
            data = {"time": f"{now:%H:%M}"}
        return SkillResult(speech=speech, data=data)
