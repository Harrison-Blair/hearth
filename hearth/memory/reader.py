"""EventReader: read-only, cursor-based pull interface over the event log.

The Layer-2 seam a future background indexer (Graphiti/FalkorDB) attaches to.
No writes, no coupling to EventLog.append.
"""
from __future__ import annotations

import json

from hearth.memory.log import Event, EventLog


class EventReader:
    def __init__(self, log: EventLog) -> None:
        self._log = log

    def read_since(self, cursor: int, limit: int) -> list[Event]:
        """Return events with `id > cursor`, ascending by `id`, capped at `limit`."""
        rows = self._log._conn.execute(
            "SELECT id, session_id, turn_id, ts_utc, type, provenance, payload_json "
            "FROM events WHERE id > ? ORDER BY id LIMIT ?",
            (cursor, limit),
        ).fetchall()

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

    def latest_cursor(self) -> int:
        """Return the max event id, or 0 when the log is empty."""
        row = self._log._conn.execute("SELECT MAX(id) FROM events").fetchone()
        return row[0] or 0
