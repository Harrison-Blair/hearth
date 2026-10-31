"""Append-only daily JSONL event log."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from .clock import utc_now

EventName = Literal[
    "connected",
    "auth_rejected",
    "user_text",
    "reply",
    "llm_error",
    "disconnected",
]


class EventLog:
    """Write events to ``<directory>/YYYY-MM-DD.jsonl`` without rewriting prior lines."""

    def __init__(
        self,
        directory: Path,
        *,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._directory = directory
        self._clock = clock

    def write(
        self,
        event: EventName,
        *,
        device_id: str | None,
        turn_id: str | None = None,
        **details: object,
    ) -> None:
        now = self._clock().astimezone(UTC)
        record: dict[str, object] = {
            "ts": now.isoformat(),
            "event": event,
            "device_id": device_id,
        }
        if turn_id is not None:
            record["turn_id"] = turn_id
        record.update(details)
        line = json.dumps(record, ensure_ascii=False)
        self._directory.mkdir(parents=True, exist_ok=True)
        path = self._directory / f"{now.date().isoformat()}.jsonl"
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
