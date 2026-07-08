"""SQLite-backed store of pending reminders and timers.

The store is the single source of truth: a reminder lives here until it fires (the
scheduler hard-deletes it then), so it survives a restart. Timestamps are UTC
epoch seconds (time.time()), which
makes ``due`` comparisons timezone-free; only the skill converts a wall-clock
"5 pm" into an epoch.

``kind`` separates timers from reminders explicitly ('timer' / 'reminder'), and
``label`` carries an optional timer name ("pasta"). Both fall out of a guarded
in-place migration, so a database created before they existed upgrades on open.

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
    created_at REAL    NOT NULL,
    kind       TEXT    NOT NULL DEFAULT 'reminder',
    label      TEXT,
    interval   REAL
);
CREATE INDEX IF NOT EXISTS ix_reminders_due ON reminders (due_at);
"""

_COLUMNS = "id, due_at, speech, kind, label, interval"


@dataclass
class Reminder:
    id: int
    due_at: float
    speech: str
    kind: str = "reminder"
    label: str | None = None
    # Recurring reminders repeat every ``interval`` seconds; None is a one-shot.
    interval: float | None = None


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
        self._migrate()
        self._conn.commit()

    def _migrate(self) -> None:
        """Add the kind/label columns to a pre-existing table. The timer backfill
        runs only in the same pass that adds ``kind`` — a later reminder whose
        speech happens to match the timer sentence keeps its stored kind."""
        columns = {
            row["name"]
            for row in self._conn.execute("PRAGMA table_info(reminders)").fetchall()
        }
        if "kind" not in columns:
            self._conn.execute(
                "ALTER TABLE reminders ADD COLUMN kind TEXT NOT NULL DEFAULT 'reminder'"
            )
            self._conn.execute(
                "UPDATE reminders SET kind = 'timer' WHERE speech = 'Your timer is done.'"
            )
        if "label" not in columns:
            self._conn.execute("ALTER TABLE reminders ADD COLUMN label TEXT")
        if "interval" not in columns:
            self._conn.execute("ALTER TABLE reminders ADD COLUMN interval REAL")

    def add(
        self,
        due_at: float,
        speech: str,
        *,
        created_at: float,
        kind: str = "reminder",
        label: str | None = None,
        interval: float | None = None,
    ) -> int:
        cur = self._conn.execute(
            "INSERT INTO reminders (due_at, speech, created_at, kind, label, interval)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (due_at, speech, created_at, kind, label, interval),
        )
        self._conn.commit()
        return int(cur.lastrowid)

    @staticmethod
    def _row(r: sqlite3.Row) -> Reminder:
        return Reminder(r["id"], r["due_at"], r["speech"], r["kind"], r["label"], r["interval"])

    def due(self, now: float) -> list[Reminder]:
        rows = self._conn.execute(
            f"SELECT {_COLUMNS} FROM reminders WHERE due_at <= ? ORDER BY due_at",
            (now,),
        ).fetchall()
        return [self._row(r) for r in rows]

    def pending(self, now: float, kind: str | None = None) -> list[Reminder]:
        """Reminders still in the future, soonest first (for listing); ``kind``
        narrows to timers or reminders."""
        sql = f"SELECT {_COLUMNS} FROM reminders WHERE due_at > ?"
        params: list = [now]
        if kind is not None:
            sql += " AND kind = ?"
            params.append(kind)
        rows = self._conn.execute(sql + " ORDER BY due_at", params).fetchall()
        return [self._row(r) for r in rows]

    def delete(self, reminder_id: int) -> None:
        self._conn.execute("DELETE FROM reminders WHERE id = ?", (reminder_id,))
        self._conn.commit()

    def delete_pending(self, now: float, kind: str | None = None) -> int:
        """Delete every future reminder (of ``kind``, when given); return how many
        were removed."""
        sql = "DELETE FROM reminders WHERE due_at > ?"
        params: list = [now]
        if kind is not None:
            sql += " AND kind = ?"
            params.append(kind)
        cur = self._conn.execute(sql, params)
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
