"""SQLite-backed store of pending reminders (and timers).

The store is the single source of truth: a reminder lives here until it fires (the
scheduler hard-deletes it then), so it survives a restart. Timestamps are UTC
epoch seconds (time.time()), which
makes ``due`` comparisons timezone-free; only the skill converts a wall-clock
"5 pm" into an epoch.

All methods are synchronous: each is a single sub-millisecond statement run on the
event-loop thread, so wrapping them in a thread (which would trip sqlite3's
check_same_thread) buys nothing.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

_SCHEMA = """
CREATE TABLE IF NOT EXISTS reminders (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    due_at     REAL    NOT NULL,
    speech     TEXT    NOT NULL,
    created_at REAL    NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_reminders_due ON reminders (due_at);
"""


@dataclass
class Reminder:
    id: int
    due_at: float
    speech: str


class ReminderStore:
    def __init__(self, db_path: str) -> None:
        self._conn = sqlite3.connect(db_path)
        self._conn.row_factory = sqlite3.Row
        # WAL lets the scheduler's reads and writes overlap without blocking, and
        # synchronous=NORMAL trades a vanishingly small crash-durability window for
        # far fewer fsyncs. No-ops on an in-memory db. (WAL spawns -wal/-shm sidecars.)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def add(self, due_at: float, speech: str, *, created_at: float) -> int:
        cur = self._conn.execute(
            "INSERT INTO reminders (due_at, speech, created_at) VALUES (?, ?, ?)",
            (due_at, speech, created_at),
        )
        self._conn.commit()
        return int(cur.lastrowid)

    def due(self, now: float) -> list[Reminder]:
        rows = self._conn.execute(
            "SELECT id, due_at, speech FROM reminders WHERE due_at <= ? ORDER BY due_at",
            (now,),
        ).fetchall()
        return [Reminder(r["id"], r["due_at"], r["speech"]) for r in rows]

    def pending(self, now: float) -> list[Reminder]:
        """Reminders still in the future, soonest first (for listing)."""
        rows = self._conn.execute(
            "SELECT id, due_at, speech FROM reminders WHERE due_at > ? ORDER BY due_at",
            (now,),
        ).fetchall()
        return [Reminder(r["id"], r["due_at"], r["speech"]) for r in rows]

    def delete(self, reminder_id: int) -> None:
        self._conn.execute("DELETE FROM reminders WHERE id = ?", (reminder_id,))
        self._conn.commit()

    def delete_pending(self, now: float) -> int:
        """Delete every future reminder; return how many were removed."""
        cur = self._conn.execute(
            "DELETE FROM reminders WHERE due_at > ?", (now,)
        )
        self._conn.commit()
        return cur.rowcount

    def update_due(self, reminder_id: int, due_at: float) -> None:
        self._conn.execute(
            "UPDATE reminders SET due_at = ? WHERE id = ?", (due_at, reminder_id)
        )
        self._conn.commit()

    def update_speech(self, reminder_id: int, speech: str) -> None:
        self._conn.execute(
            "UPDATE reminders SET speech = ? WHERE id = ?", (speech, reminder_id)
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()
