"""Which calendar events Calcifer should not bring up unprompted.

Three sources, checked together: title patterns added by voice (persisted in
CalendarStateStore), title patterns from config.yaml, and a hidden tag the
user puts in an event's description in the Google Calendar UI — the only way
to flag personal-calendar events at the source, since the service account is
read-only there. Blocking hides events from queries and watcher announcements
only; explicit requests (manage, event reminders) still see everything.
"""

from __future__ import annotations

from assistant.calendar.base import CalendarEvent, speakable_title
from assistant.storage.calendar_state import CalendarStateStore


def _normalize(text: str) -> str:
    """Match on what would be spoken: emoji stripped, lowercased."""
    return speakable_title(text).lower()


class EventBlocklist:
    def __init__(
        self,
        store: CalendarStateStore,
        *,
        config_patterns: list[str],
        hidden_tag: str = "[hidden]",
    ) -> None:
        self._store = store
        self._config = [p for p in (_normalize(p) for p in config_patterns) if p]
        self._hidden_tag = hidden_tag.lower()

    def is_blocked(self, event: CalendarEvent) -> bool:
        if self._hidden_tag and self._hidden_tag in event.description.lower():
            return True
        title = _normalize(event.title)
        return any(p in title for p in self._config + self._store.blocked_patterns())

    def block(self, pattern: str, *, created_at: float) -> None:
        self._store.add_blocked(_normalize(pattern), created_at=created_at)

    def unblock(self, pattern: str) -> bool:
        """Remove the voice-added pattern; False when it wasn't stored."""
        return self._store.remove_blocked(_normalize(pattern)) > 0

    def in_config(self, pattern: str) -> bool:
        """Whether the pattern would stay blocked by config even after unblock."""
        wanted = _normalize(pattern)
        return any(p in wanted or wanted in p for p in self._config)

    def patterns(self) -> list[str]:
        """All active patterns for a spoken listing, voice-added first."""
        merged = self._store.blocked_patterns()
        merged.extend(p for p in self._config if p not in merged)
        return merged
