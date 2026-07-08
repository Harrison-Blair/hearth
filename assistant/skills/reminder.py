"""Reminder skill.

Parses the spoken request, persists a reminder to the store (the scheduler speaks
it when due), and confirms. Timers live in the same store under ``kind='timer'``
but belong to TimerSkill; every query here filters to ``kind='reminder'``.
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
    humanize_interval,
    parse_management,
    resolve_time,
)
from assistant.skills.base import Skill, local_now
from assistant.storage.reminders import Reminder, ReminderStore

_TEXT_ARG = {
    "type": "object",
    "properties": {"text": {"type": "string", "description": "the request, verbatim"}},
    "required": ["text"],
}
_NO_ARGS = {"type": "object", "properties": {}}


class ReminderSkill(Skill):
    name = "reminder"
    intents = {"reminder", "list_reminders", "manage_reminders"}
    tool_specs = {
        "reminder": {
            "description": (
                "Create a reminder for a future time, after a delay, or repeating at a "
                "regular interval (e.g. every 15 minutes)."
            ),
            "parameters": _TEXT_ARG,
        },
        "list_reminders": {
            "description": "Read back the user's pending reminders.",
            "parameters": _NO_ARGS,
        },
        "manage_reminders": {
            "description": (
                "Cancel, reschedule, or rename existing reminders — a specific one "
                "or all of them."
            ),
            "parameters": _TEXT_ARG,
        },
    }

    def __init__(
        self,
        store: ReminderStore,
        llm: LLMProvider,
        now: Callable[[], datetime] = local_now,
    ) -> None:
        self._store = store
        self._llm = llm
        self._now = now  # injectable for deterministic tests

    async def handle(self, cmd: Command, intent: Intent) -> SkillResult:
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
        n = self._store.delete_pending(self._now().timestamp(), kind="reminder")
        noun = "reminder" if n == 1 else "reminders"
        return SkillResult(f"Okay, I've cancelled all {n} of your {noun}.")

    def _handle_list(self) -> SkillResult:
        now_ts = self._now().timestamp()
        pending = self._store.pending(now_ts, kind="reminder")
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
    def _message_of(reminder: Reminder) -> str:
        """The bare reminder text (defensive fallback: unprefixed speech as-is)."""
        if reminder.speech.startswith("Reminder: "):
            return reminder.speech[len("Reminder: ") :].rstrip(".")
        return reminder.speech.rstrip(".")

    @classmethod
    def _describe(cls, reminder: Reminder, now_ts: float) -> str:
        when = (
            humanize_interval(reminder.interval)
            if reminder.interval
            else humanize(reminder.due_at - now_ts)
        )
        return f"{cls._message_of(reminder)} {when}"

    async def _handle_reminder(self, text: str) -> SkillResult:
        now = self._now()
        parsed = await extract_reminder(text, self._llm, now)
        if parsed is None:
            return SkillResult(
                "Sorry, I didn't catch when to remind you.", success=False
            )
        self._store.add(
            parsed.due_at,
            f"Reminder: {parsed.message}.",
            created_at=now.timestamp(),
            interval=parsed.interval,
        )
        when = (
            humanize_interval(parsed.interval)
            if parsed.interval
            else humanize(parsed.due_at - now.timestamp())
        )
        return SkillResult(f"Okay, I'll remind you to {parsed.message} {when}.")

    _CANCEL_WORDS = (
        "cancel", "clear", "delete", "forget", "remove", "get rid of", "wipe", "erase"
    )
    # Standalone match so "all" fires for "cancel all" but not inside "call mom"
    # or a hyphenated name like "all-hands" (a bare \b treats the hyphen as a
    # word boundary, which would wrongly trigger a delete-everything).
    _BULK_RE = re.compile(r"(?<![\w-])(all|everything|every|them all)(?![\w-])")
    # "clear my reminders" names no specific target, so it means all of them even
    # without the word "all": a cancel verb followed only by determiners/qualifiers
    # then plural "reminders" at the end of the utterance. A targeted request
    # always has content after "reminders" ("... the reminders about the meeting")
    # or a non-filler word before it ("... the meeting reminders").
    _FILLER = r"(?:\s+(?:my|the|all|any|of|existing|current|pending|old))*"
    _BARE_PLURAL_RE = re.compile(
        r"\b(?:" + "|".join(_CANCEL_WORDS) + r")" + _FILLER + r"\s+reminders\W*(?:please\W*)?$"
    )

    @classmethod
    def _is_bulk_cancel(cls, text: str) -> bool:
        lowered = text.lower()
        if not any(c in lowered for c in cls._CANCEL_WORDS):
            return False
        return bool(cls._BULK_RE.search(lowered)) or bool(cls._BARE_PLURAL_RE.search(lowered))

    async def _handle_manage(self, text: str) -> SkillResult:
        now = self._now()
        now_ts = now.timestamp()
        pending = self._store.pending(now_ts, kind="reminder")
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
            return SkillResult(
                f"Okay, I'll remind you to {message} {humanize(due - now_ts)} instead."
            )

        # rename
        if not action.new_message:
            return SkillResult(
                "I couldn't tell which reminder you meant.", success=False
            )
        self._store.update_speech(target.id, f"Reminder: {action.new_message}.")
        return SkillResult(f"Okay, that reminder now says {action.new_message}.")
