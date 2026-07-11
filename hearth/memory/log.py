"""EventLog: append-only SQLite event store.

Schema: events(id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT,
turn_id TEXT, ts_utc TEXT, type TEXT, provenance TEXT, payload_json TEXT).
No update/delete method is exposed — the log is append-only.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

# type accepts the full enum; this feather emits only user_input/final_answer.
EVENT_TYPES = {
    "user_input",
    "routing_decision",
    "tool_call",
    "observation",
    "final_answer",
    "error",
}


@dataclass
class Event:
    id: int
    session_id: str
    turn_id: str
    ts_utc: str
    type: str
    provenance: str
    payload: dict


class EventLog:
    def __init__(self, db_path: str) -> None:
        self._conn = sqlite3.connect(db_path)
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                turn_id TEXT,
                ts_utc TEXT,
                type TEXT,
                provenance TEXT,
                payload_json TEXT
            )
            """
        )
        self._conn.commit()

    def append(
        self,
        session_id: str,
        turn_id: str,
        type: str,
        provenance: str,
        payload: dict,
    ) -> Event:
        ts_utc = datetime.now(timezone.utc).isoformat()
        payload_json = json.dumps(payload)
        cursor = self._conn.execute(
            "INSERT INTO events (session_id, turn_id, ts_utc, type, provenance, payload_json) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (session_id, turn_id, ts_utc, type, provenance, payload_json),
        )
        self._conn.commit()
        return Event(
            id=cursor.lastrowid,
            session_id=session_id,
            turn_id=turn_id,
            ts_utc=ts_utc,
            type=type,
            provenance=provenance,
            payload=payload,
        )

    def read_session(self, session_id: str, limit: int | None = None) -> list[Event]:
        """Return session events in `id` order, optionally capped to the most
        recent `limit` rows (still returned oldest-first)."""
        if limit is None:
            rows = self._conn.execute(
                "SELECT id, session_id, turn_id, ts_utc, type, provenance, payload_json "
                "FROM events WHERE session_id = ? ORDER BY id",
                (session_id,),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT id, session_id, turn_id, ts_utc, type, provenance, payload_json "
                "FROM events WHERE session_id = ? ORDER BY id DESC LIMIT ?",
                (session_id, limit),
            ).fetchall()
            rows = list(reversed(rows))

        return [
            Event(
                id=row[0],
                session_id=row[1],
                turn_id=row[2],
                ts_utc=row[3],
                type=row[4],
                provenance=row[5],
                payload=json.loads(row[6]),
            )
            for row in rows
        ]
