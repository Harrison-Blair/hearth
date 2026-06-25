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

# Prefixes peeled off (longest first) to recover the bare reminder message.
_MESSAGE_PREFIXES = ("remind me to", "remind me", "to")


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
    if match:
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
        data = json.loads(await llm.complete(prompt, json=True))
    except Exception as exc:  # noqa: BLE001 - any LLM/JSON failure -> graceful None
        log.warning("LLM reminder extraction failed: %s", exc)
        return None

    message = (data.get("message") or "").strip().strip(".?!,").strip()
    if not message:
        return None

    delay = data.get("delay_seconds")
    if isinstance(delay, (int, float)) and delay > 0:
        return now.timestamp() + float(delay), message

    due = _next_occurrence(now, data.get("at_time"))
    return (due, message) if due is not None else None


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
