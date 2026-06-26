"""Extract *when* and *what* from a spoken reminder/timer request.

Hybrid strategy: a fast offline regex handles relative durations ("in 30
seconds", "for five minutes" — and every timer), and the local LLM is the
fallback for absolute wall-clock times ("at 5 pm to call mom") that regex and
spoken word-numbers handle poorly.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta

from assistant.llm.base import LLMProvider

log = logging.getLogger(__name__)

_WORD_NUMBERS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
    "fourteen": 14, "fifteen": 15, "twenty": 20, "thirty": 30, "forty": 40,
    "fifty": 50, "sixty": 60,
}
_UNIT_SECONDS = {
    "hour": 3600, "hr": 3600, "minute": 60, "min": 60, "second": 1, "sec": 1,
}

_NUM = r"\d+|" + "|".join(sorted(_WORD_NUMBERS, key=len, reverse=True))
_UNIT = "|".join(sorted(_UNIT_SECONDS, key=len, reverse=True))
# Optionally consume a leading "in/for/after" so it's stripped from the message too.
_DURATION_RE = re.compile(
    rf"(?:\b(?:in|for|after)\s+)?({_NUM})\s+({_UNIT})s?\b", re.IGNORECASE
)

# A clock time anywhere in the request ("at 6 pm", "9:30", "8 o'clock", "noon").
# When present, the duration regex must not win: "a 10 minute workout at 6 pm" is
# a 6 pm reminder, not a 10-minute one — defer to the LLM, which disambiguates.
_CLOCK_RE = re.compile(
    r"\b\d{1,2}\s*(?:am|pm)\b|\b\d{1,2}:\d{2}\b|\bo'?clock\b|\bnoon\b|\bmidnight\b",
    re.IGNORECASE,
)

# Prefixes peeled off (longest first) to recover the bare reminder message.
_MESSAGE_PREFIXES = ("remind me to", "remind me", "to")


@dataclass
class ManagementAction:
    """A parsed request to change an existing reminder. ``action`` is "cancel",
    "reschedule", "rename", or "none" (when the target/intent couldn't be read)."""

    action: str
    target_index: int | None = None
    new_at_time: str | None = None
    new_delay_seconds: float | None = None
    new_message: str | None = None


def parse_duration(text: str) -> float | None:
    """Seconds for a relative duration phrase, or None if there isn't one."""
    match = _DURATION_RE.search(text.lower())
    return _match_seconds(match) if match else None


async def extract_reminder(
    text: str, llm: LLMProvider, now: datetime
) -> tuple[float, str] | None:
    """Return (due_at_epoch, message) for a reminder request, or None if the
    time couldn't be determined."""
    lowered = text.lower()
    match = _DURATION_RE.search(lowered)
    if match and not _CLOCK_RE.search(lowered):
        message = _strip_message(lowered[: match.start()] + " " + lowered[match.end() :])
        if not message:
            return None
        return now.timestamp() + _match_seconds(match), message
    return await _extract_via_llm(text, llm, now)


def humanize(seconds: float) -> str:
    """A spoken-friendly relative phrase, e.g. 'in 5 minutes'."""
    seconds = int(round(seconds))
    if seconds < 60:
        n, unit = seconds, "second"
    elif seconds < 3600:
        n, unit = seconds // 60, "minute"
    else:
        n, unit = seconds // 3600, "hour"
    return f"in {n} {unit}{'' if n == 1 else 's'}"


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


def _match_seconds(match: re.Match) -> float:
    count_tok, unit = match.group(1).lower(), match.group(2).lower()
    count = int(count_tok) if count_tok.isdigit() else _WORD_NUMBERS[count_tok]
    return float(count * _UNIT_SECONDS[unit])


def _strip_message(remainder: str) -> str:
    s = " ".join(remainder.split()).strip(".?!,").strip()
    for prefix in _MESSAGE_PREFIXES:
        if s.startswith(prefix + " ") or s == prefix:
            s = s[len(prefix) :].strip()
            break
    return s.strip(".?!,").strip()


async def _extract_via_llm(
    text: str, llm: LLMProvider, now: datetime
) -> tuple[float, str] | None:
    prompt = (
        f"The current local time is {now:%Y-%m-%d %H:%M (%A)}.\n"
        "Extract when to remind the user and the message from their request.\n"
        "Reply with ONLY a JSON object: "
        '{"delay_seconds": <int or null>, "at_time": "<HH:MM 24-hour or null>", '
        '"message": "<the thing to be reminded of>"}.\n'
        "Rules: use delay_seconds ONLY for explicit relative durations like "
        '"in 10 minutes". Use at_time for any clock time like "5 pm" or "half past '
        'eight" (a clock time is NOT a delay). Set the unused field to null.\n'
        'Example: "remind me in 10 minutes to stretch" -> '
        '{"delay_seconds": 600, "at_time": null, "message": "stretch"}\n'
        'Example: "remind me at 9 am to take pills" -> '
        '{"delay_seconds": null, "at_time": "09:00", "message": "take pills"}\n'
        f'Request: "{text}"'
    )
    try:
        data = json.loads(await llm.complete(prompt, json=True, label="timespec"))
    except Exception as exc:  # noqa: BLE001 - any LLM/JSON failure -> graceful None
        log.warning("LLM reminder extraction failed: %s", exc)
        return None

    message = (data.get("message") or "").strip().strip(".?!,").strip()
    if not message:
        return None

    due = resolve_time(
        now, delay_seconds=data.get("delay_seconds"), at_time=data.get("at_time")
    )
    return (due, message) if due is not None else None


def resolve_time(
    now: datetime, *, delay_seconds: float | None, at_time: str | None
) -> float | None:
    """Epoch for a relative delay or an absolute clock time, or None for neither."""
    if isinstance(delay_seconds, (int, float)) and delay_seconds > 0:
        return now.timestamp() + float(delay_seconds)
    return _next_occurrence(now, at_time)


def _next_occurrence(now: datetime, at_time: str | None) -> float | None:
    if not at_time:
        return None
    try:
        hour, minute = (int(p) for p in at_time.split(":"))
        target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    except (ValueError, AttributeError):
        return None
    if target <= now:
        target += timedelta(days=1)
    return target.timestamp()


async def parse_management(
    text: str, pending_descriptions: list[str], llm: LLMProvider, now: datetime
) -> ManagementAction:
    """Read a cancel/reschedule/rename request against the *current* pending list.

    The list is passed in soonest-first (1-based), so the LLM can resolve both
    positional ("the first one") and message ("the call-mom one") targets to an
    index. Returns ``action="none"`` on any LLM/JSON failure (graceful)."""
    numbered = "\n".join(f"{i}. {d}" for i, d in enumerate(pending_descriptions, 1))
    prompt = (
        f"The current local time is {now:%Y-%m-%d %H:%M (%A)}.\n"
        "The user has these pending reminders (1-based, soonest first):\n"
        f"{numbered}\n"
        "Decide what to do with them based on the request.\n"
        "Reply with ONLY a JSON object: "
        '{"action": "<cancel|reschedule|rename|none>", '
        '"target_index": <the number from the list, or null>, '
        '"new_delay_seconds": <int or null>, "new_at_time": "<HH:MM 24-hour or null>", '
        '"new_message": "<new reminder text, or null>"}.\n'
        "Rules: target_index identifies which reminder, by position or by what it is "
        'about. Use action "reschedule" with a new time (new_delay_seconds for a '
        'relative duration, new_at_time for a clock time) to change when it fires; '
        '"rename" with new_message to change what it says; "cancel" to delete it. Use '
        '"none" if you cannot tell which reminder is meant.\n'
        'Example: "cancel the first one" -> '
        '{"action": "cancel", "target_index": 1, "new_delay_seconds": null, '
        '"new_at_time": null, "new_message": null}\n'
        'Example: "move my call-mom reminder to 6 pm" -> '
        '{"action": "reschedule", "target_index": 2, "new_delay_seconds": null, '
        '"new_at_time": "18:00", "new_message": null}\n'
        f'Request: "{text}"'
    )
    try:
        data = json.loads(await llm.complete(prompt, json=True, label="timespec"))
    except Exception as exc:  # noqa: BLE001 - any LLM/JSON failure -> graceful none
        log.warning("LLM reminder management parse failed: %s", exc)
        return ManagementAction(action="none")

    action = data.get("action")
    if action not in ("cancel", "reschedule", "rename"):
        return ManagementAction(action="none")
    index = data.get("target_index")
    return ManagementAction(
        action=action,
        target_index=_coerce_index(index),
        new_at_time=data.get("new_at_time"),
        new_delay_seconds=data.get("new_delay_seconds"),
        new_message=(data.get("new_message") or None),
    )
