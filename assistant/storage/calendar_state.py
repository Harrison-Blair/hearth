"""SQLite-backed calendar state: watcher dedupe and voice-blocked titles.

announced_events is keyed by (event_id, start_at) so the same event is
announced once per start time: a rescheduled event gets a new start epoch and
is announced again with the new time, while a restart inside the lead window
stays silent. blocked_titles holds normalized title patterns added by the
"stop bringing up ..." voice command. Timestamps are UTC epoch seconds,
matching ReminderStore.

All methods are synchronous for the same reason as ReminderStore: each is a
single sub-millisecond statement on the event-loop thread.
"""

from __future__ import annotations

import sqlite3

_SCHEMA = """
CREATE TABLE IF NOT EXISTS announced_events (
    event_id     TEXT NOT NULL,
    start_at     REAL NOT NULL,
    announced_at REAL NOT NULL,
    PRIMARY KEY (event_id, start_at)
);
CREATE TABLE IF NOT EXISTS blocked_titles (
    pattern    TEXT PRIMARY KEY,
    created_at REAL NOT NULL
);
"""


class CalendarStateStore:
    def __init__(self, db_path: str) -> None:
        self._conn = sqlite3.connect(db_path)
        # Same pragmas as ReminderStore: overlapping reads/writes, fewer fsyncs.
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def was_announced(self, event_id: str, start_at: float) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM announced_events WHERE event_id = ? AND start_at = ?",
            (event_id, start_at),
        ).fetchone()
        return row is not None

    def mark(self, event_id: str, start_at: float, *, announced_at: float) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO announced_events (event_id, start_at, announced_at) "
            "VALUES (?, ?, ?)",
            (event_id, start_at, announced_at),
        )
        self._conn.commit()

    def purge_before(self, ts: float) -> int:
        """Drop rows for events that started before ts; return how many."""
        cur = self._conn.execute("DELETE FROM announced_events WHERE start_at < ?", (ts,))
        self._conn.commit()
        return cur.rowcount

    def add_blocked(self, pattern: str, *, created_at: float) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO blocked_titles (pattern, created_at) VALUES (?, ?)",
            (pattern, created_at),
        )
        self._conn.commit()

    def remove_blocked(self, pattern: str) -> int:
        """Drop the pattern if stored; return how many rows were removed."""
        cur = self._conn.execute("DELETE FROM blocked_titles WHERE pattern = ?", (pattern,))
        self._conn.commit()
        return cur.rowcount

    def blocked_patterns(self) -> list[str]:
        rows = self._conn.execute(
            "SELECT pattern FROM blocked_titles ORDER BY created_at"
        ).fetchall()
        return [row[0] for row in rows]

    def close(self) -> None:
        self._conn.close()
