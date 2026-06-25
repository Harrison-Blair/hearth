"""Reminder and timer skill.

Parses the spoken request, persists a reminder to the store (the scheduler speaks
it when due), and confirms. A timer is just an anonymous reminder that announces
"Your timer is done."
"""

from __future__ import annotations

from datetime import datetime
from typing import Callable

from assistant.core.events import Command, Intent, SkillResult
from assistant.llm.base import LLMProvider
from assistant.nlu.timespec import extract_reminder, humanize, parse_duration
from assistant.skills.base import Skill
from assistant.storage.reminders import ReminderStore


def _local_now() -> datetime:
    return datetime.now().astimezone()


class ReminderSkill(Skill):
    name = "reminder"
    intents = {"reminder", "timer"}

    def __init__(
        self,
        store: ReminderStore,
        llm: LLMProvider,
        now: Callable[[], datetime] = _local_now,
    ) -> None:
        self._store = store
        self._llm = llm
        self._now = now  # injectable for deterministic tests

    async def handle(self, cmd: Command, intent: Intent) -> SkillResult:
        if intent.type == "timer":
            return self._handle_timer(cmd.text)
        return await self._handle_reminder(cmd.text)

    def _handle_timer(self, text: str) -> SkillResult:
        seconds = parse_duration(text)
        if seconds is None:
            return SkillResult(
                "Sorry, I didn't catch how long to set the timer for.", success=False
            )
        now = self._now()
        self._store.add(
            now.timestamp() + seconds, "Your timer is done.", created_at=now.timestamp()
        )
        return SkillResult(f"Okay, timer set for {humanize(seconds).removeprefix('in ')}.")

    async def _handle_reminder(self, text: str) -> SkillResult:
        now = self._now()
        parsed = await extract_reminder(text, self._llm, now)
        if parsed is None:
            return SkillResult(
                "Sorry, I didn't catch when to remind you.", success=False
            )
        due_at, message = parsed
        self._store.add(due_at, f"Reminder: {message}.", created_at=now.timestamp())
        return SkillResult(
            f"Okay, I'll remind you to {message} {humanize(due_at - now.timestamp())}."
        )
