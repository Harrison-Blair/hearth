"""Intermediate event types for the loop -> veneer emit path.

Defined here so the boundary is frozen even though nothing emits through it
until FTHR-006 (tool rounds); FTHR-003's veneer supplies a sink that
serializes it to the wire.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Awaitable, Callable


@dataclass
class ToolActivity:
    turn_id: str
    phase: str  # "start" | "end"
    label: str


EventSink = Callable[[object], Awaitable[None]]


async def null_sink(event: object) -> None:
    """Default no-op sink."""
    return None
