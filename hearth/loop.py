"""Loop.run_turn: persona-voiced local orchestrator with a nested
consult_brain tool, and the shared `run_react_rounds` ReAct engine used by
both the top-level orchestrator turn and a nested brain consult.

Thought -> Action -> Observation: the top-level turn is always served by the
local tier, carrying a Calcifer persona system prompt, and offers exactly one
tool -- `consult_brain(query)` -- gated on `router.brain_available()`.
Calling it runs a nested ReAct round on the remote tier over the real data
tools (see `hearth.tools.consult`); its findings return as an observation the
orchestrator incorporates into its own answer.
"""
from __future__ import annotations

import asyncio
import logging

from hearth.brain.base import BrainResult, Message
from hearth.brain.router import Router
from hearth.events import EventSink, ToolActivity, null_sink
from hearth.memory.log import EventLog
from hearth.persona import restyle

logger = logging.getLogger(__name__)


async def run_react_rounds(
    *,
    brain,
    messages: list[Message],
    tools,
    dispatch,
    round_cap: int,
    log: EventLog,
    session_id: str,
    turn_id: str,
    emit: EventSink,
    label_for,
) -> BrainResult:
    """Thought -> Action -> Observation over `brain`, capped at `round_cap`
    tool rounds. Shared by the orchestrator's own turn and a nested brain
    consult -- no duplicated ReAct logic between the two call sites."""
    result = await brain.complete(messages, tools=tools)

    round_count = 0
    while result.tool_calls and round_count < round_cap:
        round_count += 1
        messages.append(
            Message(role="assistant", content=result.text, tool_calls=result.tool_calls)
        )
        for call in result.tool_calls:
            label = label_for(call.name)

            await emit(ToolActivity(turn_id, "start", label))
            log.append(
                session_id,
                turn_id,
                "tool_call",
                "loop",
                {"name": call.name, "arguments": call.arguments},
            )
            try:
                observation = await dispatch(call.name, call.arguments)
            except Exception as exc:  # tool failure becomes an observation, not a crash
                observation = f"error: {exc}"
            log.append(
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

        result = await brain.complete(messages, tools=tools)

    if result.tool_calls and not result.text:
        result.text = "I wasn't able to finish that within the allowed tool rounds."
    return result


class Loop:
    def __init__(
        self, router: Router, log: EventLog, config, consult=None, transcript=None
    ) -> None:
        self._router = router
        self._log = log
        self._config = config
        self._consult = consult
        self._transcript = transcript

    def _log_model(self, role: str, selection) -> None:
        try:
            model = self._config.llm.backends[selection.backend_name].model
            logger.info(
                "%s turn model backend=%s tier=%s model=%s",
                role,
                selection.backend_name,
                selection.tier,
                model,
            )
        except Exception:  # never let logging break a turn (AC-5)
            pass

    def _append_transcript(self, session_id: str, line: str) -> None:
        if self._transcript is None:
            return
        try:
            self._transcript.append(session_id, line)
        except Exception:  # never let a transcript write break a turn (AC-5)
            pass

    async def run_turn(
        self,
        session_id: str,
        turn_id: str,
        transcript: str,
        emit: EventSink = null_sink,
    ) -> str:
        self._log.append(session_id, turn_id, "user_input", "user", {"text": transcript})
        self._append_transcript(session_id, f"user: {transcript}")

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

        messages: list[Message] = [
            Message(role="system", content=self._config.persona.system_prompt)
        ]
        for event in bounded_events:
            if event.type == "user_input":
                messages.append(Message(role="user", content=event.payload["text"]))
            elif event.type == "final_answer":
                messages.append(Message(role="assistant", content=event.payload["text"]))

        consult_offered = self._consult is not None and self._router.brain_available()
        tools = [self._consult.spec] if consult_offered else None

        selection = self._router.select()
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
        self._log_model("orchestrator", selection)

        # Stashed so `_consult_dispatch` (whose shape is fixed to
        # `dispatch(name, args) -> str` by `run_react_rounds`) can forward
        # this turn's session_id/turn_id/emit to the injected `BrainConsult`.
        self._current_session_id = session_id
        self._current_turn_id = turn_id
        self._current_emit = emit

        def label_for(name: str) -> str:
            spec = next((s for s in (tools or []) if s.name == name), None)
            return spec.label if spec else name

        try:
            result = await asyncio.wait_for(
                run_react_rounds(
                    brain=selection.brain,
                    messages=messages,
                    tools=tools,
                    dispatch=self._consult_dispatch,
                    round_cap=self._config.agent.max_consult_rounds,
                    log=self._log,
                    session_id=session_id,
                    turn_id=turn_id,
                    emit=emit,
                    label_for=label_for,
                ),
                timeout=self._config.agent.turn_timeout_s,
            )
            answer_text = result.text or ""
        except asyncio.TimeoutError:
            answer_text = "That took too long — here's what I have so far."

        answer = await restyle(answer_text, ctx=None)

        self._log.append(session_id, turn_id, "final_answer", "brain", {"text": answer})
        self._append_transcript(session_id, f"answer: {answer}")
        return answer

    async def _consult_dispatch(self, name: str, args: dict) -> str:
        return await self._consult(
            self._current_session_id,
            self._current_turn_id,
            args["query"],
            self._current_emit,
        )
