"""Extract calendar-event details from spoken requests via the local LLM.

Same shape as nlu/timespec.py (which stays reminder-only): current-time
preamble, ONLY-JSON reply, worked examples, and a graceful None/none result on
any LLM or JSON failure so the skill can apologize instead of crashing.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from assistant.llm.base import LLMProvider

log = logging.getLogger(__name__)

_DEFAULT_DURATION_MINUTES = 60
_DEFAULT_LEAD_MINUTES = 15


@dataclass
class ExtractedEvent:
    title: str
    start: datetime  # tz-aware (inherits now's tz)
    end: datetime


@dataclass
class EventManagementAction:
    """A parsed request to change an existing event. ``action`` is "cancel",
    "reschedule", "rename", or "none" (when the target/intent couldn't be read)."""

    action: str
    target_index: int | None = None
    new_date: str | None = None  # YYYY-MM-DD
    new_start_time: str | None = None  # HH:MM 24-hour
    new_title: str | None = None


@dataclass
class EventReminderRequest:
    target_index: int | None
    lead_minutes: int


@dataclass
class BlockRequest:
    """A parsed request to mute/unmute events by title. ``action`` is "block",
    "unblock", "list", or "none" (when the intent couldn't be read)."""

    action: str
    pattern: str | None = None


def _coerce_index(value) -> int | None:
    """A 1-based list index from the model, tolerating the JSON quirks of a
    numeric string ("2") or a whole float (2.0); None for anything else."""
    if isinstance(value, bool):  # bool is an int subclass; not a real index
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value.is_integer() else None
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _coerce_minutes(value, default: int) -> int:
    minutes = _coerce_index(value)  # same int coercion rules
    return minutes if minutes is not None and minutes > 0 else default


def resolve_start(
    now: datetime, date_str: str | None, time_str: str | None, *, roll_past: bool = True
) -> datetime | None:
    """A tz-aware start from the model's date/time fields. A null date means
    now's date, rolling to the next day if that clock time has already passed
    (disable roll_past when `now` is an existing event's start, whose date a
    bare new time should keep)."""
    try:
        hour, minute = (int(p) for p in time_str.split(":"))
    except (ValueError, AttributeError, TypeError):
        return None
    if date_str:
        try:
            year, month, day = (int(p) for p in date_str.split("-"))
            return now.replace(
                year=year, month=month, day=day, hour=hour, minute=minute,
                second=0, microsecond=0,
            )
        except (ValueError, AttributeError):
            return None
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if roll_past and target <= now:
        target += timedelta(days=1)
    return target


async def extract_event(text: str, llm: LLMProvider, now: datetime) -> ExtractedEvent | None:
    """Title, start, and end for a create-event request, or None if the
    details couldn't be determined."""
    prompt = (
        f"The current local time is {now:%Y-%m-%d %H:%M (%A)}.\n"
        "Extract the calendar event the user wants to create.\n"
        "Reply with ONLY a JSON object: "
        '{"title": "<short event title>", "date": "<YYYY-MM-DD or null>", '
        '"start_time": "<HH:MM 24-hour>", "duration_minutes": <int or null>}.\n'
        "Rules: resolve weekday names to the NEXT occurrence of that day as a "
        "date. Use null date when no day is mentioned. duration_minutes is null "
        "unless the user gives a length or an end time.\n"
        'Example (today is 2026-07-06, Monday): "add a dentist appointment '
        'Tuesday at 3 pm" -> {"title": "dentist appointment", "date": '
        '"2026-07-07", "start_time": "15:00", "duration_minutes": null}\n'
        'Example: "put lunch with Sam on my calendar at noon for 90 minutes" -> '
        '{"title": "lunch with Sam", "date": null, "start_time": "12:00", '
        '"duration_minutes": 90}\n'
        f'Request: "{text}"'
    )
    try:
        data = json.loads(await llm.complete(prompt, json=True, label="calendar"))
    except Exception as exc:  # noqa: BLE001 - any LLM/JSON failure -> graceful None
        log.warning("LLM event extraction failed: %s", exc)
        return None

    title = (data.get("title") or "").strip().strip(".?!,").strip()
    start = resolve_start(now, data.get("date"), data.get("start_time"))
    if not title or start is None:
        return None
    duration = _coerce_minutes(data.get("duration_minutes"), _DEFAULT_DURATION_MINUTES)
    return ExtractedEvent(title=title, start=start, end=start + timedelta(minutes=duration))


async def parse_event_management(
    text: str, event_descriptions: list[str], llm: LLMProvider, now: datetime
) -> EventManagementAction:
    """Read a cancel/reschedule/rename request against the current event list
    (1-based, soonest first). Returns ``action="none"`` on any failure."""
    numbered = "\n".join(f"{i}. {d}" for i, d in enumerate(event_descriptions, 1))
    prompt = (
        f"The current local time is {now:%Y-%m-%d %H:%M (%A)}.\n"
        "These are the user's upcoming calendar events (1-based, soonest first):\n"
        f"{numbered}\n"
        "Decide what to do with them based on the request.\n"
        "Reply with ONLY a JSON object: "
        '{"action": "<cancel|reschedule|rename|none>", '
        '"target_index": <the number from the list, or null>, '
        '"new_date": "<YYYY-MM-DD or null>", '
        '"new_start_time": "<HH:MM 24-hour or null>", '
        '"new_title": "<new event title, or null>"}.\n'
        "Rules: target_index identifies which event, by position or by what it "
        'is about. Use "reschedule" with new_start_time (and new_date if a day '
        'is mentioned) to move it; "rename" with new_title to retitle it; '
        '"cancel" to delete it. Use "none" if you cannot tell which event is '
        "meant.\n"
        'Example: "cancel the dentist appointment" -> '
        '{"action": "cancel", "target_index": 1, "new_date": null, '
        '"new_start_time": null, "new_title": null}\n'
        'Example: "move the dentist appointment to 4 pm" -> '
        '{"action": "reschedule", "target_index": 1, "new_date": null, '
        '"new_start_time": "16:00", "new_title": null}\n'
        f'Request: "{text}"'
    )
    try:
        data = json.loads(await llm.complete(prompt, json=True, label="calendar"))
    except Exception as exc:  # noqa: BLE001 - any LLM/JSON failure -> graceful none
        log.warning("LLM event management parse failed: %s", exc)
        return EventManagementAction(action="none")

    action = data.get("action")
    if action not in ("cancel", "reschedule", "rename"):
        return EventManagementAction(action="none")
    return EventManagementAction(
        action=action,
        target_index=_coerce_index(data.get("target_index")),
        new_date=data.get("new_date"),
        new_start_time=data.get("new_start_time"),
        new_title=(data.get("new_title") or None),
    )


async def parse_block_request(text: str, llm: LLMProvider) -> BlockRequest:
    """Read a mute/unmute/list request over event titles. The pattern is free
    text (no event list needed). Returns ``action="none"`` on any failure."""
    prompt = (
        "The user controls which calendar events the assistant mentions.\n"
        "Reply with ONLY a JSON object: "
        '{"action": "<block|unblock|list>", '
        '"pattern": "<the event name or phrase to match, or null>"}.\n'
        'Rules: "block" to stop mentioning matching events, "unblock" to '
        'resume mentioning them, "list" when the user asks which events are '
        "muted. pattern is the event title or phrase, null for list.\n"
        'Example: "stop bringing up bedtime" -> '
        '{"action": "block", "pattern": "bedtime"}\n'
        'Example: "you can mention my wake up alarm again" -> '
        '{"action": "unblock", "pattern": "wake up alarm"}\n'
        'Example: "which events are you ignoring" -> '
        '{"action": "list", "pattern": null}\n'
        f'Request: "{text}"'
    )
    try:
        data = json.loads(await llm.complete(prompt, json=True, label="calendar"))
    except Exception as exc:  # noqa: BLE001 - any LLM/JSON failure -> graceful none
        log.warning("LLM block-request parse failed: %s", exc)
        return BlockRequest(action="none")

    action = data.get("action")
    if action not in ("block", "unblock", "list"):
        return BlockRequest(action="none")
    pattern = (data.get("pattern") or "").strip() or None
    return BlockRequest(action=action, pattern=pattern)


async def parse_event_reminder(
    text: str, event_descriptions: list[str], llm: LLMProvider, now: datetime
) -> EventReminderRequest:
    """Which event to be reminded about and how many minutes before. The lead
    defaults to 15 when unstated; target_index is None on any failure."""
    numbered = "\n".join(f"{i}. {d}" for i, d in enumerate(event_descriptions, 1))
    prompt = (
        f"The current local time is {now:%Y-%m-%d %H:%M (%A)}.\n"
        "These are the user's upcoming calendar events (1-based, soonest first):\n"
        f"{numbered}\n"
        "The user wants a reminder before one of these events.\n"
        "Reply with ONLY a JSON object: "
        '{"target_index": <the number from the list, or null>, '
        '"lead_minutes": <minutes before the event, or null>}.\n'
        "Rules: target_index identifies which event, by position or by what it "
        "is about; null if you cannot tell. lead_minutes is null when the user "
        "doesn't say how far ahead.\n"
        'Example: "remind me 30 minutes before my dentist appointment" -> '
        '{"target_index": 1, "lead_minutes": 30}\n'
        f'Request: "{text}"'
    )
    try:
        data = json.loads(await llm.complete(prompt, json=True, label="calendar"))
    except Exception as exc:  # noqa: BLE001 - any LLM/JSON failure -> graceful none
        log.warning("LLM event reminder parse failed: %s", exc)
        return EventReminderRequest(target_index=None, lead_minutes=_DEFAULT_LEAD_MINUTES)

    return EventReminderRequest(
        target_index=_coerce_index(data.get("target_index")),
        lead_minutes=_coerce_minutes(data.get("lead_minutes"), _DEFAULT_LEAD_MINUTES),
    )
