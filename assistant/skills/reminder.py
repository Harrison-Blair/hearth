"""Reminder and timer skill.

Parses the spoken request, persists a reminder to the store (the scheduler speaks
it when due), and confirms. A timer is just an anonymous reminder that announces
"Your timer is done."
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Callable

from assistant.core.events import Command, Intent, SkillResult
from assistant.llm.base import LLMProvider
from assistant.nlu.timespec import (
    extract_reminder,
    humanize,
    parse_duration,
    parse_management,
    resolve_time,
)
from assistant.skills.base import Skill
from assistant.storage.reminders import Reminder, ReminderStore


def _local_now() -> datetime:
    return datetime.now().astimezone()


_TEXT_ARG = {
    "type": "object",
    "properties": {"text": {"type": "string", "description": "the request, verbatim"}},
    "required": ["text"],
}
_NO_ARGS = {"type": "object", "properties": {}}


class ReminderSkill(Skill):
    name = "reminder"
    intents = {"reminder", "timer", "list_reminders", "manage_reminders"}
    tool_specs = {
        "timer": {
            "description": "Start a countdown timer for a relative duration (e.g. 5 minutes).",
            "parameters": {
                "type": "object",
                "properties": {
                    "duration": {"type": "string", "description": "e.g. '5 minutes', '30 seconds'"}
                },
                "required": ["duration"],
            },
        },
        "reminder": {
            "description": "Create a reminder for a future time or after a delay.",
            "parameters": _TEXT_ARG,
        },
        "list_reminders": {
            "description": "Read back the user's pending reminders and timers.",
            "parameters": _NO_ARGS,
        },
        "manage_reminders": {
            "description": "Cancel, reschedule, or rename an existing reminder or timer.",
            "parameters": _TEXT_ARG,
        },
    }

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
        if intent.type == "list_reminders":
            return self._handle_list()
        if intent.type == "manage_reminders":
            return await self._handle_manage(cmd.text)
        return await self._handle_reminder(cmd.text)

    _AFFIRMATIONS = ("yes", "yeah", "yep", "confirm", "do it", "go ahead", "sure")

    async def handle_reply(self, cmd: Command) -> SkillResult:
        """Confirm the pending bulk-cancel. A cancelled/silent reply arrives as an
        empty transcript, so anything not clearly affirmative aborts."""
        lowered = cmd.text.lower()
        if not any(word in lowered for word in self._AFFIRMATIONS):
            return SkillResult("Okay, I'll leave them.")
        n = self._store.delete_pending(self._now().timestamp())
        noun = "reminder" if n == 1 else "reminders"
        return SkillResult(f"Okay, I've cancelled all {n} of your {noun}.")

    def _handle_list(self) -> SkillResult:
        now_ts = self._now().timestamp()
        pending = self._store.pending(now_ts)
        if not pending:
            return SkillResult("You don't have any reminders set.")
        items = [self._describe(r, now_ts) for r in pending]
        if len(items) == 1:
            listing = items[0]
        else:
            listing = ", ".join(items[:-1]) + ", and " + items[-1]
        noun = "reminder" if len(items) == 1 else "reminders"
        return SkillResult(f"You have {len(items)} {noun}: {listing}.")

    @staticmethod
    def _message_of(reminder: Reminder) -> str | None:
        """The bare reminder text, or None for a timer (speech not prefixed)."""
        if reminder.speech.startswith("Reminder: "):
            return reminder.speech[len("Reminder: ") :].rstrip(".")
        return None  # speech is "Your timer is done."

    @classmethod
    def _describe(cls, reminder: Reminder, now_ts: float) -> str:
        when = humanize(reminder.due_at - now_ts)
        message = cls._message_of(reminder)
        return f"{message} {when}" if message is not None else f"a timer {when}"

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

    _CANCEL_WORDS = ("cancel", "clear", "delete", "forget", "remove")
    # Standalone match so "all" fires for "cancel all" but not inside "call mom"
    # or a hyphenated name like "all-hands" (a bare \b treats the hyphen as a
    # word boundary, which would wrongly trigger a delete-everything).
    _BULK_RE = re.compile(r"(?<![\w-])(all|everything|every|them all)(?![\w-])")

    @classmethod
    def _is_bulk_cancel(cls, text: str) -> bool:
        lowered = text.lower()
        return any(c in lowered for c in cls._CANCEL_WORDS) and bool(
            cls._BULK_RE.search(lowered)
        )

    async def _handle_manage(self, text: str) -> SkillResult:
        now = self._now()
        now_ts = now.timestamp()
        pending = self._store.pending(now_ts)
        if not pending:
            return SkillResult("You don't have any reminders to cancel or change.")

        if self._is_bulk_cancel(text):
            n = len(pending)
            noun = "reminder" if n == 1 else "reminders"
            return SkillResult(
                f"That will cancel all {n} {noun}. Should I go ahead?",
                expects_reply=True,
            )

        action = await parse_management(
            text, [self._describe(r, now_ts) for r in pending], self._llm, now
        )
        if action.target_index is None or not (1 <= action.target_index <= len(pending)):
            return SkillResult(
                "I couldn't tell which reminder you meant.", success=False
            )
        target = pending[action.target_index - 1]
        message = self._message_of(target)

        if action.action == "cancel":
            self._store.delete(target.id)
            if message is None:
                return SkillResult("Okay, I've cancelled the timer.")
            return SkillResult(f"Okay, I've cancelled your reminder to {message}.")

        if action.action == "reschedule":
            due = resolve_time(
                now,
                delay_seconds=action.new_delay_seconds,
                at_time=action.new_at_time,
            )
            if due is None:
                return SkillResult(
                    "Sorry, I didn't catch the new time.", success=False
                )
            self._store.update_due(target.id, due)
            label = message if message is not None else "the timer"
            return SkillResult(
                f"Okay, I'll remind you to {label} {humanize(due - now_ts)} instead."
            )

        # rename
        if not action.new_message:
            return SkillResult(
                "I couldn't tell which reminder you meant.", success=False
            )
        self._store.update_speech(target.id, f"Reminder: {action.new_message}.")
        return SkillResult(f"Okay, that reminder now says {action.new_message}.")
