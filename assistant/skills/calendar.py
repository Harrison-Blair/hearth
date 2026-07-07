"""Google Calendar skill.

Reads events from the user's personal calendar and Calcifer's own calendar;
creates/changes events only on Calcifer's calendar (the personal one is
read-only for the service account, which is also the natural guard against
touching the user's own events). Event reminders are plain ReminderStore rows,
so the existing scheduler speaks them and they show up in list/manage
reminders for free. Every provider failure degrades to a spoken apology.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Callable

from assistant.calendar.base import CalendarEvent, CalendarProvider, speakable_title
from assistant.calendar.blocklist import EventBlocklist
from assistant.calendar.extraction import (
    extract_event,
    parse_block_request,
    parse_event_management,
    parse_event_reminder,
    resolve_start,
)
from assistant.core.events import Command, Intent, SkillResult
from assistant.llm.base import LLMProvider
from assistant.nlu.timespec import humanize
from assistant.skills.base import Skill, local_now
from assistant.storage.reminders import ReminderStore

log = logging.getLogger(__name__)

_TEXT_ARG = {
    "type": "object",
    "properties": {"text": {"type": "string", "description": "the request, verbatim"}},
    "required": ["text"],
}

_CANT_REACH = "Sorry, I can't reach your calendar right now."
_MANAGE_WINDOW_DAYS = 14
_SPOKEN_EVENT_CAP = 8  # a week can hold dozens of events; don't read them all
_COLLAPSE_AT = 3  # a title repeated this often in a multi-day window reads as one group

_WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
_speakable = speakable_title


def _spoken_time(dt: datetime) -> str:
    hour = dt.strftime("%I").lstrip("0")
    ampm = dt.strftime("%p")
    return f"{hour}:{dt.minute:02d} {ampm}" if dt.minute else f"{hour} {ampm}"


def _spoken_day(dt: datetime, now: datetime) -> str:
    delta = (dt.date() - now.date()).days
    if delta == 0:
        return "today"
    if delta == 1:
        return "tomorrow"
    return f"on {dt.strftime('%A')}"


def _spoken_length(minutes: int) -> str:
    if minutes % 60 == 0 and minutes > 0:
        hours = minutes // 60
        return f"{hours} hour{'' if hours == 1 else 's'}"
    return f"{minutes} minutes"


def _join(items: list[str]) -> str:
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + ", and " + items[-1]


class CalendarSkill(Skill):
    name = "calendar"
    intents = {
        "calendar_query",
        "calendar_create",
        "calendar_manage",
        "calendar_event_reminder",
        "calendar_watch",
        "calendar_block",
    }
    tool_specs = {
        "calendar_query": {
            "description": "Read the user's upcoming calendar events.",
            "parameters": {
                "type": "object",
                "properties": {
                    "day": {
                        "type": "string",
                        "description": "'today', 'tomorrow', or a weekday; omit for the next 7 days",
                    }
                },
            },
        },
        "calendar_create": {
            "description": "Create a new calendar event with a title, date, and time.",
            "parameters": _TEXT_ARG,
        },
        "calendar_manage": {
            "description": "Cancel, reschedule, or rename an event Calcifer created on its calendar.",
            "parameters": _TEXT_ARG,
        },
        "calendar_event_reminder": {
            "description": "Set a reminder some minutes before an existing calendar event.",
            "parameters": _TEXT_ARG,
        },
        "calendar_watch": {
            "description": "Turn automatic upcoming-event announcements on or off.",
            "parameters": {
                "type": "object",
                "properties": {
                    "enabled": {
                        "type": "boolean",
                        "description": "true to start watching, false to stop",
                    }
                },
                "required": ["enabled"],
            },
        },
        "calendar_block": {
            "description": (
                "Stop mentioning certain calendar events, resume mentioning "
                "them, or list which are muted."
            ),
            "parameters": _TEXT_ARG,
        },
    }

    def __init__(
        self,
        provider: CalendarProvider,
        llm: LLMProvider,
        reminder_store: ReminderStore,
        watcher,  # anything with a bool `enabled` attribute
        *,
        blocklist: EventBlocklist,
        personal_id: str,
        calcifer_id: str,
        now: Callable[[], datetime] = local_now,
    ) -> None:
        self._provider = provider
        self._llm = llm
        self._reminders = reminder_store
        self._watcher = watcher
        self._blocklist = blocklist
        self._personal_id = personal_id
        self._calcifer_id = calcifer_id
        self._now = now  # injectable for deterministic tests

    async def handle(self, cmd: Command, intent: Intent) -> SkillResult:
        if intent.type == "calendar_watch":
            return self._handle_watch(intent.slots.get("enabled"), cmd.text)
        if intent.type == "calendar_block":  # no provider call; can't lose the calendar
            return await self._handle_block(intent.slots.get("text") or cmd.text)
        try:
            if intent.type == "calendar_query":
                return await self._handle_query(intent.slots.get("day"))
            if intent.type == "calendar_create":
                return await self._handle_create(intent.slots.get("text") or cmd.text)
            if intent.type == "calendar_manage":
                return await self._handle_manage(intent.slots.get("text") or cmd.text)
            return await self._handle_event_reminder(intent.slots.get("text") or cmd.text)
        except Exception as exc:  # noqa: BLE001 - remote is optional; degrade to speech
            log.warning("calendar request failed: %s", exc, exc_info=True)
            return SkillResult(_CANT_REACH, success=False)

    # -- query ------------------------------------------------------------

    async def _handle_query(self, day) -> SkillResult:
        now = self._now()
        start, end, label = self._window(day, now)
        events = await self._fetch(
            [self._personal_id, self._calcifer_id], time_min=start, time_max=end
        )
        events = [e for e in events if not self._blocklist.is_blocked(e)]
        if not events:
            return SkillResult(f"Nothing on your calendar {label}.")

        single_day = (end - start) <= timedelta(days=1)
        if single_day:
            spoken = [self._describe(e, now, with_day=False) for e in events]
        else:
            spoken = self._collapse(events, now)
        overflow = len(spoken) - _SPOKEN_EVENT_CAP
        if overflow > 0:
            spoken = spoken[:_SPOKEN_EVENT_CAP]
        noun = "event" if len(events) == 1 else "events"
        listing = _join(spoken)
        tail = f", and {overflow} more" if overflow > 0 else ""
        return SkillResult(f"You have {len(events)} {noun} {label}: {listing}{tail}.")

    @staticmethod
    def _window(day, now: datetime) -> tuple[datetime, datetime, str]:
        """[start, end) plus the spoken label for a day word, defaulting to the
        next 7 days. The window opens at `now`, not midnight, so past events
        today aren't read back."""
        midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
        word = (day or "").strip().lower()
        if word == "today":
            return now, midnight + timedelta(days=1), "today"
        if word == "tomorrow":
            start = midnight + timedelta(days=1)
            return start, start + timedelta(days=1), "tomorrow"
        if word in _WEEKDAYS:
            ahead = (_WEEKDAYS.index(word) - now.weekday()) % 7
            if ahead == 0:
                return now, midnight + timedelta(days=1), "today"
            start = midnight + timedelta(days=ahead)
            return start, start + timedelta(days=1), f"on {start.strftime('%A')}"
        return now, now + timedelta(days=7), "in the next 7 days"

    @staticmethod
    def _describe(event: CalendarEvent, now: datetime, *, with_day: bool) -> str:
        title = _speakable(event.title)
        when = "all day" if event.all_day else f"at {_spoken_time(event.start)}"
        if with_day:
            return f"{title} {_spoken_day(event.start, now)} {when}"
        return f"{title} {when}"

    @classmethod
    def _collapse(cls, events: list[CalendarEvent], now: datetime) -> list[str]:
        """Spoken fragments for a multi-day listing, reading a title repeated
        _COLLAPSE_AT+ times as one group ("bedtime at 10 PM on 6 days") in the
        position of its first occurrence; everything else stays individual."""
        groups: dict[str, list[CalendarEvent]] = {}
        for event in events:  # events arrive start-sorted
            groups.setdefault(_speakable(event.title).lower(), []).append(event)

        spoken: list[str] = []
        collapsed: set[str] = set()
        for event in events:
            key = _speakable(event.title).lower()
            group = groups[key]
            if len(group) < _COLLAPSE_AT:
                spoken.append(cls._describe(event, now, with_day=True))
            elif key not in collapsed:
                collapsed.add(key)
                spoken.append(cls._describe_group(group))
        return spoken

    @staticmethod
    def _describe_group(group: list[CalendarEvent]) -> str:
        title = _speakable(group[0].title)
        days = len({e.start.date() for e in group})
        if days != len(group):  # repeats within a day; "on N days" would mislead
            return f"{title} {len(group)} times"
        times = {None if e.all_day else (e.start.hour, e.start.minute) for e in group}
        if len(times) == 1 and None not in times:
            return f"{title} at {_spoken_time(group[0].start)} on {days} days"
        return f"{title} on {days} days"

    # -- create -----------------------------------------------------------

    async def _handle_create(self, text: str) -> SkillResult:
        now = self._now()
        parsed = await extract_event(text, self._llm, now)
        if parsed is None:
            return SkillResult(
                "Sorry, I didn't catch the event's name or time.", success=False
            )
        event = await self._provider.create_event(
            self._calcifer_id, title=parsed.title, start=parsed.start, end=parsed.end
        )
        minutes = int((parsed.end - parsed.start).total_seconds() // 60)
        return SkillResult(
            f"Okay, {_speakable(event.title)} {_spoken_day(event.start, now)} "
            f"at {_spoken_time(event.start)} for {_spoken_length(minutes)}."
        )

    # -- manage -----------------------------------------------------------

    async def _handle_manage(self, text: str) -> SkillResult:
        now = self._now()
        events = await self._fetch(
            [self._calcifer_id],
            time_min=now,
            time_max=now + timedelta(days=_MANAGE_WINDOW_DAYS),
        )
        if not events:
            return SkillResult("There are no events on my calendar to change.")

        descriptions = [self._describe(e, now, with_day=True) for e in events]
        action = await parse_event_management(text, descriptions, self._llm, now)
        if action.target_index is None or not (1 <= action.target_index <= len(events)):
            return SkillResult("I couldn't tell which event you meant.", success=False)
        target = events[action.target_index - 1]
        title = _speakable(target.title)

        if action.action == "cancel":
            await self._provider.delete_event(target.calendar_id, target.id)
            return SkillResult(f"Okay, I've cancelled {title}.")

        if action.action == "reschedule":
            # A bare new time ("move it to 4 pm") keeps the event's own date;
            # resolve_start's null-date default (today) is for creating events.
            if action.new_date:
                new_start = resolve_start(now, action.new_date, action.new_start_time)
            else:
                new_start = resolve_start(
                    target.start, None, action.new_start_time, roll_past=False
                )
            if new_start is None:
                return SkillResult("Sorry, I didn't catch the new time.", success=False)
            length = (target.end - target.start) if target.end else timedelta(hours=1)
            await self._provider.update_event(
                target.calendar_id, target.id, start=new_start, end=new_start + length
            )
            return SkillResult(
                f"Okay, I've moved {title} to {_spoken_day(new_start, now)} "
                f"at {_spoken_time(new_start)}."
            )

        # rename
        if not action.new_title:
            return SkillResult("I couldn't tell which event you meant.", success=False)
        await self._provider.update_event(target.calendar_id, target.id, title=action.new_title)
        return SkillResult(f"Okay, that event is now called {_speakable(action.new_title)}.")

    # -- event reminder ---------------------------------------------------

    async def _handle_event_reminder(self, text: str) -> SkillResult:
        now = self._now()
        events = await self._fetch(
            [self._personal_id, self._calcifer_id],
            time_min=now,
            time_max=now + timedelta(days=_MANAGE_WINDOW_DAYS),
        )
        if not events:
            return SkillResult("There's nothing coming up on your calendar to remind you about.")

        descriptions = [self._describe(e, now, with_day=True) for e in events]
        request = await parse_event_reminder(text, descriptions, self._llm, now)
        if request.target_index is None or not (1 <= request.target_index <= len(events)):
            return SkillResult("I couldn't tell which event you meant.", success=False)
        target = events[request.target_index - 1]
        title = _speakable(target.title)

        due = target.start.timestamp() - request.lead_minutes * 60
        if due <= now.timestamp():
            return SkillResult(f"{title} starts too soon for that reminder.", success=False)
        self._reminders.add(
            due,
            f"Reminder: {title} starts in {request.lead_minutes} minutes.",
            created_at=now.timestamp(),
        )
        return SkillResult(
            f"Okay, I'll remind you {request.lead_minutes} minutes before {title}, "
            f"{humanize(due - now.timestamp())}."
        )

    # -- watch toggle -----------------------------------------------------

    _OFF_WORDS = ("stop", "off", "disable", "quit", "don't", "do not", "no longer")

    def _handle_watch(self, enabled, text: str) -> SkillResult:
        if isinstance(enabled, str):  # a JSON-coerced "true"/"false"
            enabled = enabled.strip().lower() not in ("false", "no", "off", "0")
        if not isinstance(enabled, bool):
            # Tool call carried no usable flag; read the request itself.
            lowered = text.lower()
            enabled = not any(w in lowered for w in self._OFF_WORDS)
        self._watcher.enabled = enabled
        if enabled:
            return SkillResult("Okay, I'm watching your calendar.")
        return SkillResult("Okay, I'll stop announcing events.")

    # -- block toggle -------------------------------------------------------

    async def _handle_block(self, text: str) -> SkillResult:
        request = await parse_block_request(text, self._llm)

        if request.action == "list":
            patterns = self._blocklist.patterns()
            if not patterns:
                return SkillResult("I'm not ignoring any events.")
            return SkillResult(f"I'm not bringing up {_join(patterns)}.")

        if request.pattern is None or request.action == "none":
            return SkillResult(
                "I didn't catch which event you meant.", success=False
            )

        if request.action == "block":
            self._blocklist.block(request.pattern, created_at=self._now().timestamp())
            return SkillResult(f"Okay, I won't bring up {request.pattern} anymore.")

        # unblock
        removed = self._blocklist.unblock(request.pattern)
        if removed and self._blocklist.in_config(request.pattern):
            return SkillResult(
                f"Okay, I'll mention {request.pattern} again, though it's "
                "still muted in my config file."
            )
        if removed:
            return SkillResult(f"Okay, I'll mention {request.pattern} again.")
        if self._blocklist.in_config(request.pattern):
            return SkillResult(
                f"{request.pattern} is muted in my config file; I can't "
                "unmute it by voice."
            )
        return SkillResult(f"I wasn't ignoring anything called {request.pattern}.")

    # -- shared -----------------------------------------------------------

    async def _fetch(
        self, calendar_ids: list[str], *, time_min: datetime, time_max: datetime
    ) -> list[CalendarEvent]:
        events: list[CalendarEvent] = []
        for calendar_id in calendar_ids:
            events.extend(
                await self._provider.list_events(
                    calendar_id, time_min=time_min, time_max=time_max
                )
            )
        events.sort(key=lambda e: e.start)
        return events
