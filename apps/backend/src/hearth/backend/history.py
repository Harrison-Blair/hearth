"""In-memory, process-wide conversation history."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TypedDict

from .clock import utc_now


class ChatMessage(TypedDict):
    role: str
    content: str


@dataclass(frozen=True, slots=True)
class Turn:
    """One completed exchange in the household thread."""

    device_id: str
    user_text: str
    reply_text: str
    timestamp: datetime


class History:
    """One household thread shared by every device.

    A turn snapshots the recent history when it starts, so concurrent turns do
    not wait for one another. A turn is appended only after its reply is done.
    """

    def __init__(
        self,
        *,
        window_minutes: int,
        max_turns: int,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._window = timedelta(minutes=window_minutes)
        self._max_turns = max_turns
        self._clock = clock
        self._turns: list[Turn] = []

    def context(
        self,
        device_id: str,
        text: str,
        *,
        now: datetime | None = None,
    ) -> list[ChatMessage]:
        """Build the LLM messages for a new turn from a history snapshot."""
        moment = self._clock() if now is None else now
        cutoff = moment - self._window
        recent = [turn for turn in self._turns if turn.timestamp > cutoff]
        selected = recent[-self._max_turns :]
        messages: list[ChatMessage] = []
        for turn in selected:
            messages.append({"role": "user", "content": f"[{turn.device_id}] {turn.user_text}"})
            messages.append({"role": "assistant", "content": turn.reply_text})
        messages.append({"role": "user", "content": f"[{device_id}] {text}"})
        return messages

    def append(self, turn: Turn) -> None:
        """Append a completed turn to the household thread."""
        self._turns.append(turn)
