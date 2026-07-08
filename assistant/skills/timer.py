"""Timer skill: countdown timers, distinct from reminders.

A timer is a ``kind='timer'`` row in the shared reminder store — same scheduler,
same firing/announcement path — with an optional name ("pasta") carried in
``label``. Duration parsing is the offline ``parse_duration`` regex; no LLM.
"""

from __future__ import annotations

from datetime import datetime
from typing import Callable

from assistant.core.events import Command, Intent, SkillResult
from assistant.nlu.timespec import humanize, parse_duration
from assistant.skills.base import Skill, local_now
from assistant.storage.reminders import Reminder, ReminderStore

_NAME_ARG = {
    "type": "string",
    "description": "the timer's name, e.g. 'pasta'; omit for an unnamed timer",
}


class TimerSkill(Skill):
    name = "timer"
    intents = {"timer", "list_timers", "cancel_timer"}
    tool_specs = {
        "timer": {
            "description": "Start a countdown timer for a relative duration (e.g. 5 minutes).",
            "parameters": {
                "type": "object",
                "properties": {
                    "duration": {
                        "type": "string", "description": "e.g. '5 minutes', '30 seconds'"
                    },
                    "name": _NAME_ARG,
                },
                "required": ["duration"],
            },
        },
        "list_timers": {
            "description": "Read back the user's running timers and how long is left.",
            "parameters": {"type": "object", "properties": {}},
        },
        "cancel_timer": {
            "description": "Cancel a running timer, by name when it has one.",
            "parameters": {
                "type": "object",
                "properties": {"name": _NAME_ARG},
            },
        },
    }

    def __init__(
        self, store: ReminderStore, now: Callable[[], datetime] = local_now
    ) -> None:
        self._store = store
        self._now = now  # injectable for deterministic tests

    async def handle(self, cmd: Command, intent: Intent) -> SkillResult:
        if intent.type == "list_timers":
            return self._handle_list()
        if intent.type == "cancel_timer":
            return self._handle_cancel(intent.slots.get("name"))
        return self._handle_set(
            intent.slots.get("duration") or cmd.text, intent.slots.get("name")
        )

    def _timers(self) -> list[Reminder]:
        return self._store.pending(self._now().timestamp(), kind="timer")

    @staticmethod
    def _describe(timer: Reminder, now_ts: float) -> str:
        when = humanize(timer.due_at - now_ts)
        return f"the {timer.label} timer {when}" if timer.label else f"a timer {when}"

    def _handle_set(self, text: str, name: str | None) -> SkillResult:
        seconds = parse_duration(text)
        if seconds is None:
            return SkillResult(
                "Sorry, I didn't catch how long to set the timer for.", success=False
            )
        name = (name or "").strip() or None
        speech = f"Your {name} timer is done." if name else "Your timer is done."
        now_ts = self._now().timestamp()
        self._store.add(
            now_ts + seconds, speech, created_at=now_ts, kind="timer", label=name
        )
        prefix = f"{name} " if name else ""
        duration = humanize(seconds).removeprefix("in ")
        return SkillResult(f"Okay, {prefix}timer set for {duration}.")

    def _handle_list(self) -> SkillResult:
        now_ts = self._now().timestamp()
        timers = self._timers()
        if not timers:
            return SkillResult("You don't have any timers running.")
        items = [self._describe(t, now_ts) for t in timers]
        listing = items[0] if len(items) == 1 else ", ".join(items[:-1]) + ", and " + items[-1]
        noun = "timer" if len(items) == 1 else "timers"
        return SkillResult(f"You have {len(items)} {noun}: {listing}.")

    def _handle_cancel(self, name: str | None) -> SkillResult:
        now_ts = self._now().timestamp()
        timers = self._timers()
        if not timers:
            return SkillResult("You don't have any timers running.")

        name = (name or "").strip()
        if name:
            lowered = name.lower()
            match = next(
                (t for t in timers if t.label and lowered in t.label.lower()), None
            )
            if match is None:
                return SkillResult(f"I couldn't find a {name} timer.", success=False)
            self._store.delete(match.id)
            return SkillResult(f"Okay, I've cancelled the {match.label} timer.")

        if len(timers) == 1:
            timer = timers[0]
            self._store.delete(timer.id)
            if timer.label:
                return SkillResult(f"Okay, I've cancelled the {timer.label} timer.")
            return SkillResult("Okay, I've cancelled the timer.")

        items = [self._describe(t, now_ts) for t in timers]
        listing = ", ".join(items[:-1]) + ", and " + items[-1]
        return SkillResult(
            f"You have {len(timers)} timers: {listing}. Which one should I cancel?",
            success=False,
        )
