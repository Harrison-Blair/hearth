"""Layer2Consumer protocol + NoOpConsumer stub, and a pull_once poll step.

Proves the read seam (EventReader) without starting any scheduler or attaching
to the daemon — that's a later phase.
"""
from __future__ import annotations

from typing import Protocol

from hearth.memory.log import Event
from hearth.memory.reader import EventReader


class Layer2Consumer(Protocol):
    async def consume(self, events: list[Event]) -> None: ...


class NoOpConsumer:
    async def consume(self, events: list[Event]) -> None:
        pass


async def pull_once(reader: EventReader, consumer: Layer2Consumer, cursor: int) -> int:
    """One poll step: read_since -> consume -> advance cursor. No scheduler."""
    events = reader.read_since(cursor, limit=1000)
    if events:
        await consumer.consume(events)
        cursor = events[-1].id
    return cursor
