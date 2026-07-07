"""Calendar provider interface.

A capability behind an ABC, like weather/ and search/: the skill and the
watcher depend only on CalendarProvider, never a concrete backend, so a
different calendar API could replace Google with a one-line change in app.py.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime

# Emoji and other symbols in event titles ("🏋️ Gym") would be spelled out or
# garbled by TTS; keep letters (any language), digits, and plain punctuation.
_UNSPEAKABLE_RE = re.compile(r"[^\w\s'&.,:;!?()/-]", re.UNICODE)


def speakable_title(title: str) -> str:
    """The event title with TTS-hostile symbols stripped."""
    return " ".join(_UNSPEAKABLE_RE.sub(" ", title).split()) or "an untitled event"


@dataclass
class CalendarEvent:
    """One calendar event. Flows only provider -> skill/watcher, so it lives
    here (like weather's Place/Forecast), not in core/events.py."""

    id: str
    calendar_id: str
    title: str
    start: datetime  # tz-aware
    end: datetime | None = None
    all_day: bool = False
    description: str = ""


class CalendarProvider(ABC):
    @abstractmethod
    async def list_events(
        self,
        calendar_id: str,
        *,
        time_min: datetime,
        time_max: datetime,
        max_results: int = 50,
    ) -> list[CalendarEvent]:
        """Events starting in [time_min, time_max), ordered by start."""

    @abstractmethod
    async def create_event(
        self, calendar_id: str, *, title: str, start: datetime, end: datetime
    ) -> CalendarEvent:
        """Create an event and return it as stored by the backend."""

    @abstractmethod
    async def update_event(
        self,
        calendar_id: str,
        event_id: str,
        *,
        title: str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> CalendarEvent:
        """Patch only the provided fields and return the updated event."""

    @abstractmethod
    async def delete_event(self, calendar_id: str, event_id: str) -> None:
        """Delete an event; an already-gone event is not an error."""

    @abstractmethod
    async def health(self) -> bool:
        """Return True if the backend is reachable and the calendars are visible."""

    async def aclose(self) -> None:
        """Release any held resources (e.g. an HTTP client). No-op by default."""
