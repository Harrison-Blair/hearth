"""Loop.run_turn: single-completion, history-aware, logged conversation turn.

No tool rounds yet (FTHR-006 adds them); `emit` is unused here beyond being
wired through, since nothing emits `ToolActivity` until FTHR-006.
"""
from __future__ import annotations

from hearth.brain.base import Message
from hearth.brain.router import Router
from hearth.events import EventSink, null_sink
from hearth.memory.log import EventLog
from hearth.persona import restyle


class Loop:
    def __init__(self, router: Router, log: EventLog, config) -> None:
        self._router = router
        self._log = log
        self._config = config

    async def run_turn(
        self,
        session_id: str,
        turn_id: str,
        transcript: str,
        emit: EventSink = null_sink,
    ) -> str:
        self._log.append(session_id, turn_id, "user_input", "user", {"text": transcript})

        # Reconstruct history from the log itself (no separate history store):
        # keep only the conversational turn types, then bound to the last
        # `max_history_turns` exchanges (2 events each) plus the current
        # turn's just-appended user_input.
        max_history_turns = self._config.conversation.max_history_turns
        turn_events = [
            event
            for event in self._log.read_session(session_id)
            if event.type in ("user_input", "final_answer")
        ]
        bounded_events = turn_events[-(max_history_turns * 2 + 1) :]

        messages: list[Message] = []
        for event in bounded_events:
            if event.type == "user_input":
                messages.append(Message(role="user", content=event.payload["text"]))
            elif event.type == "final_answer":
                messages.append(Message(role="assistant", content=event.payload["text"]))

        selection = self._router.select(tools_available=False)
        self._log.append(
            session_id,
            turn_id,
            "routing_decision",
            "router",
            {
                "tier": selection.tier,
                "backend_name": selection.backend_name,
                "reason": selection.reason,
            },
        )

        result = await selection.brain.complete(messages, tools=None)
        answer = await restyle(result.text, ctx=None)

        self._log.append(session_id, turn_id, "final_answer", "brain", {"text": answer})
        return answer
