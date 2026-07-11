"""consult_brain: the orchestrator's one tool -- a nested ReAct round on the
remote brain over the real data tools (wikipedia_search).

`wikipedia_search` never reaches the top-level orchestrator turn; it is only
callable from inside this nested loop, over the brain-side `ToolRegistry`
injected at construction. A `BrainError` (FTHR-008) or a timeout during the
consult degrades to a plain-text observation instead of raising, so a slow or
failing brain never crashes the orchestrator's turn.
"""
from __future__ import annotations

import asyncio

from hearth.brain.base import Message, ToolSpec
from hearth.brain.errors import BrainError
from hearth.brain.router import Router
from hearth.events import EventSink, null_sink
from hearth.loop import run_react_rounds
from hearth.memory.log import EventLog
from hearth.tools.registry import ToolRegistry

SPEC = ToolSpec(
    name="consult_brain",
    description=(
        "Consult an external knowledge brain for facts you don't already "
        "know (e.g. looking something up). Pass a plain-language query."
    ),
    parameters={
        "type": "object",
        "properties": {"query": {"type": "string"}},
        "required": ["query"],
    },
    label="consult",
)


class BrainConsult:
    spec = SPEC

    def __init__(
        self,
        router: Router,
        tool_registry: ToolRegistry,
        log: EventLog,
        config,
    ) -> None:
        self._router = router
        self._tool_registry = tool_registry
        self._log = log
        self._config = config

    async def __call__(
        self,
        session_id: str,
        turn_id: str,
        query: str,
        emit: EventSink = null_sink,
    ) -> str:
        selection = self._router.select(tier_override="tool")
        messages: list[Message] = [
            Message(role="system", content=self._config.persona.brain_guard_prompt),
            Message(role="user", content=query),
        ]
        tools = self._tool_registry.specs() or None

        def label_for(name: str) -> str:
            spec = next(
                (s for s in self._tool_registry.specs() if s.name == name), None
            )
            return spec.label if spec else name

        try:
            result = await asyncio.wait_for(
                run_react_rounds(
                    brain=selection.brain,
                    messages=messages,
                    tools=tools,
                    dispatch=self._tool_registry.dispatch,
                    round_cap=self._config.agent.max_tool_rounds,
                    log=self._log,
                    session_id=session_id,
                    turn_id=turn_id,
                    emit=emit,
                    label_for=label_for,
                ),
                timeout=self._config.agent.consult_timeout_s,
            )
        except BrainError:
            return "consult_brain: couldn't reach the external knowledge source right now."
        except asyncio.TimeoutError:
            return "consult_brain: that took too long, continuing without it."

        return result.text or "consult_brain: no findings."
