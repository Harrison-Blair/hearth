"""Veneer wire protocol: inbound `Request`, outbound message builders.

`serialize` is a structural whitelist: it copies only `phase`/`label` off a
`ToolActivity`, so tool query/arguments/observation/result content cannot
cross the boundary even by accident. Unknown event types raise -- fail loud,
never leak.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from hearth.brain.errors import BrainError
from hearth.events import ToolActivity

GENERIC_ERROR_MESSAGE = "the turn failed"


@dataclass
class Request:
    turn_id: str
    final_user_transcript: str


def parse_request(raw: str) -> Request:
    data = json.loads(raw)
    return Request(turn_id=data["turn_id"], final_user_transcript=data["final_user_transcript"])


def serialize(event: object) -> dict:
    """Map a core event to its wire message. Whitelist-only."""
    if isinstance(event, ToolActivity):
        return {
            "type": "tool_activity",
            "turn_id": event.turn_id,
            "phase": event.phase,
            "label": event.label,
        }
    raise TypeError(f"no wire serialization for event type {type(event).__name__}")


def answer_message(turn_id: str, text: str) -> dict:
    return {"type": "answer", "turn_id": turn_id, "text": text}


def done_message(turn_id: str) -> dict:
    return {"type": "done", "turn_id": turn_id}


def error_message(turn_id: str, message: str) -> dict:
    return {"type": "error", "turn_id": turn_id, "message": message}


def curate_error(exc: Exception) -> str:
    """What's safe to tell the client about a turn failure. Whitelist-only:
    a `BrainError`'s client-safe `.reason`, or the fixed generic message --
    never `str(exc)`, never `BrainError.detail`."""
    if isinstance(exc, BrainError):
        return exc.reason
    return GENERIC_ERROR_MESSAGE
