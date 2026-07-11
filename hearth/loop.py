"""Loop.run_turn: history-aware, logged conversation turn with ReAct tool rounds.

Thought -> Action -> Observation: when the registry offers tools and
`agent.tool_mode` isn't "off", the turn routes to the tool tier and, while the
brain keeps returning tool calls (capped at `agent.max_tool_rounds`), dispatches
each call, logs `tool_call`/`observation`, and emits a content-free
`ToolActivity` (phase + label only) through `emit` for the veneer.
"""
from __future__ import annotations

import asyncio

from hearth.brain.base import BrainResult, Message
from hearth.brain.router import Router
from hearth.events import EventSink, ToolActivity, null_sink
from hearth.memory.log import EventLog
from hearth.persona import restyle
from hearth.tools.registry import ToolRegistry


class Loop:
    def __init__(self, router: Router, log: EventLog, config, registry: ToolRegistry = None) -> None:
        self._router = router
        self._log = log
        self._config = config
        self._registry = registry if registry is not None else ToolRegistry()

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

        tool_specs = self._registry.specs()
        # Short-circuits before touching `config.agent` when there are no
        # tools registered, so callers with a minimal config (no `agent`
        # section) can still drive the pure-chat path unchanged.
        tools_available = bool(tool_specs) and self._config.agent.tool_mode != "off"

        selection = self._router.select(tools_available=tools_available)
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

        tools = tool_specs if tools_available else None
        result = await selection.brain.complete(messages, tools=tools)

        if tools_available:
            try:
                result = await asyncio.wait_for(
                    self._run_tool_rounds(
                        session_id, turn_id, messages, selection, tools, result, emit
                    ),
                    timeout=self._config.agent.turn_timeout_s,
                )
            except asyncio.TimeoutError:
                result.text = result.text or "That took too long — here's what I have so far."

        answer = await restyle(result.text or "", ctx=None)

        self._log.append(session_id, turn_id, "final_answer", "brain", {"text": answer})
        return answer

    async def _run_tool_rounds(
        self,
        session_id: str,
        turn_id: str,
        messages: list[Message],
        selection,
        tools,
        result: BrainResult,
        emit: EventSink,
    ) -> BrainResult:
        round_count = 0
        while result.tool_calls and round_count < self._config.agent.max_tool_rounds:
            round_count += 1
            messages.append(
                Message(role="assistant", content=result.text, tool_calls=result.tool_calls)
            )
            for call in result.tool_calls:
                spec = next((s for s in self._registry.specs() if s.name == call.name), None)
                label = spec.label if spec else call.name

                await emit(ToolActivity(turn_id, "start", label))
                self._log.append(
                    session_id,
                    turn_id,
                    "tool_call",
                    "loop",
                    {"name": call.name, "arguments": call.arguments},
                )
                try:
                    observation = await self._registry.dispatch(call.name, call.arguments)
                except Exception as exc:  # tool failure becomes an observation, not a crash
                    observation = f"error: {exc}"
                self._log.append(
                    session_id,
                    turn_id,
                    "observation",
                    "tool",
                    {"name": call.name, "result": observation},
                )
                await emit(ToolActivity(turn_id, "end", label))

                messages.append(
                    Message(role="tool", content=observation, tool_call_id=call.id)
                )

            result = await selection.brain.complete(messages, tools=tools)

        if result.tool_calls and not result.text:
            result.text = "I wasn't able to finish that within the allowed tool rounds."
        return result
