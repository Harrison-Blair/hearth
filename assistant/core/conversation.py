"""In-memory conversation history for one multi-turn voice exchange.

Holds the rolling user/assistant turns so the LLM can resolve references across
follow-ups. Created per conversation in the pipeline and discarded on silence;
no persistence.
"""

from __future__ import annotations

from collections import deque

from assistant.core.events import Turn


class Conversation:
    def __init__(self, max_turns: int) -> None:
        self._turns: deque[Turn] = deque(maxlen=max_turns)

    def add(self, role: str, content: str) -> None:
        self._turns.append(Turn(role, content))

    def history(self) -> list[Turn]:
        return list(self._turns)
