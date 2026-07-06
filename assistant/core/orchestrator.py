"""Hybrid tool-calling orchestrator.

Turns a transcript into a spoken result. Two paths:

1. **Fast path** — an LLM-free keyphrase/command match (``CommandEntryRouter ->
   KeyphraseRouter``) for cheap, frequent commands ("what time is it", "set a
   timer"). A confident (non-default) hit dispatches straight to the skill with
   zero LLM calls, which matters for voice latency on the Pi.
2. **Tool-calling loop** — for everything else, the model picks a tool (a skill
   intent) and fills its arguments, or answers directly from general knowledge.
   One LLM call replaces the old classify-then-answer two-call path, and the tool
   arguments populate ``Intent.slots`` for free.

The tool decision is model-agnostic (``tool_mode``): a native Ollama tool-calling
path with a prompt-coerced JSON fallback, so it degrades exactly like routing does
today — native -> JSON -> (LLM offline) general fallback, which itself speaks a
clean "couldn't reach my language model" message.

Skill speech is terminal: the chosen skill's reply is spoken as-is. A skill that
returns no speech (a pure data step) feeds its result back and the loop continues,
bounded by ``max_tool_rounds``. We deliberately stop short of a full ReAct agent —
most voice turns are one tool call or a direct answer, and extra round-trips are
expensive on-device.
"""

from __future__ import annotations

import asyncio
import json
import logging

from assistant.core.events import Command, Intent, SkillResult, ToolCall, Turn
from assistant.llm.base import ChatResponse, LLMProvider
from assistant.nlu.router import IntentRouter
from assistant.skills.base import Skill, SkillRegistry

log = logging.getLogger(__name__)


class Orchestrator:
    # Break to the general fallback if the model calls one tool name more than this
    # many times in a turn — a verifier stall re-calling the same tool otherwise
    # burns the whole round budget on a loop.
    _TOOL_REPEAT_CAP = 2

    def __init__(
        self,
        llm: LLMProvider,
        registry: SkillRegistry,
        fast_path: IntentRouter,
        *,
        tool_mode: str = "auto",
        max_tool_rounds: int = 3,
        fast_path_enabled: bool = True,
        system_prompt: str = "",
        default_intent: str = "general",
        turn_timeout_s: float = 20.0,
    ) -> None:
        self._llm = llm
        self._registry = registry
        self._fast_path = fast_path
        self._tool_mode = tool_mode
        self._max_rounds = max(1, max_tool_rounds)
        self._fast_path_enabled = fast_path_enabled
        self._system = system_prompt
        self._default_intent = default_intent
        self._turn_timeout = turn_timeout_s
        self._tools = registry.tool_schemas()
        self._tool_names = {t["function"]["name"] for t in self._tools}

    async def handle(
        self, text: str, history: list[Turn], *, spoken: bool
    ) -> tuple[SkillResult | None, Skill | None]:
        """Route one utterance to a spoken result. Returns ``(result, skill)`` where
        ``skill`` is the handler (so the caller can route a follow-up to it), or
        ``(None, None)`` when nothing could handle it. Skill exceptions propagate to
        the caller; LLM failures degrade internally to the general fallback."""
        # 1. Fast path: a confident (non-default) keyphrase/command hit skips the LLM.
        if self._fast_path_enabled:
            intent = await self._fast_path.route(text)
            if intent.type != self._default_intent:
                return await self._dispatch(intent, text, history, spoken=spoken)

        # 2. Tool-calling loop, bounded by a whole-turn budget so a stuck model
        #    can't hold the mic; on timeout we degrade to the general fallback.
        messages = self._messages(text, history)
        tool_counts: dict[str, int] = {}
        try:
            async with asyncio.timeout(self._turn_timeout):
                for _ in range(self._max_rounds):
                    try:
                        resp = await self._decide(messages)
                    except Exception as exc:  # noqa: BLE001 - LLM down -> answer offline-gracefully
                        log.warning("Tool decision failed: %s; answering from general knowledge", exc)
                        return await self._dispatch(self._fallback(text), text, history, spoken=spoken)

                    if resp.tool_calls:
                        call = resp.tool_calls[0]
                        if call.name not in self._tool_names:
                            log.warning("Model called unknown tool %r; falling back", call.name)
                            break
                        tool_counts[call.name] = tool_counts.get(call.name, 0) + 1
                        if tool_counts[call.name] > self._TOOL_REPEAT_CAP:
                            log.warning("Model re-called %r past the repeat cap; falling back", call.name)
                            break
                        skill = self._registry.get(call.name)
                        intent = Intent(type=call.name, slots=dict(call.arguments), raw_text=text)
                        result = await skill.handle(
                            Command(text, spoken=spoken, history=history), intent
                        )
                        if result.speech:
                            return result, skill  # skill speech is the spoken answer
                        messages.extend(self._tool_feedback(call, result))
                        continue

                    if resp.content:
                        return SkillResult(speech=resp.content), None
                    break
        except TimeoutError:
            log.warning("Turn exceeded %.1fs budget; answering from general knowledge", self._turn_timeout)

        # 3. No tool chosen / rounds exhausted / timed out: answer from general knowledge.
        return await self._dispatch(self._fallback(text), text, history, spoken=spoken)

    async def _dispatch(
        self, intent: Intent, text: str, history: list[Turn], *, spoken: bool
    ) -> tuple[SkillResult | None, Skill | None]:
        skill = self._registry.get(intent.type)
        if skill is None:
            return None, None
        result = await skill.handle(Command(text, spoken=spoken, history=history), intent)
        return result, skill

    def _fallback(self, text: str) -> Intent:
        return Intent(type=self._default_intent, raw_text=text)

    @staticmethod
    def _messages(text: str, history: list[Turn]) -> list[dict]:
        msgs = [{"role": t.role, "content": t.content} for t in history]
        msgs.append({"role": "user", "content": text})
        return msgs

    async def _decide(self, messages: list[dict]) -> ChatResponse:
        """One tool-selection decision, honoring ``tool_mode`` and degrading native
        -> JSON when ``auto``."""
        if self._tool_mode in ("native", "auto"):
            try:
                resp = await self._llm.chat_tools(
                    messages, system=self._system, tools=self._tools, label="agent"
                )
            except Exception as exc:  # noqa: BLE001 - native path optional under "auto"
                if self._tool_mode == "native":
                    raise
                log.warning("Native tool-calling failed: %s; trying JSON selection", exc)
            else:
                if resp.tool_calls or resp.content or self._tool_mode == "native":
                    return resp
        return await self._decide_json(messages)

    async def _decide_json(self, messages: list[dict]) -> ChatResponse:
        raw = await self._llm.complete(
            self._json_prompt(messages[-1]["content"]),
            system=self._system,
            json=True,
            label="agent",
        )
        data = json.loads(raw)
        if isinstance(data, dict):
            tool = data.get("tool")
            if isinstance(tool, str) and tool in self._tool_names:
                args = data.get("arguments")
                return ChatResponse(
                    tool_calls=[ToolCall(name=tool, arguments=args if isinstance(args, dict) else {})]
                )
            answer = data.get("answer")
            if isinstance(answer, str) and answer.strip():
                return ChatResponse(content=answer.strip())
        return ChatResponse()

    def _json_prompt(self, text: str) -> str:
        catalogue = "\n".join(
            f'- {t["function"]["name"]}: {t["function"].get("description", "")}'
            for t in self._tools
        )
        return (
            "You are a voice assistant. Either call one tool or answer directly.\n"
            "Tools:\n"
            f"{catalogue}\n"
            'Reply with ONLY a JSON object. To use a tool: '
            '{"tool": "<name>", "arguments": {<args>}}.\n'
            'To answer from general knowledge: {"answer": "<one or two short spoken sentences>"}.\n'
            f'Request: "{text}"'
        )

    @staticmethod
    def _tool_feedback(call: ToolCall, result: SkillResult) -> list[dict]:
        # A no-speech tool result is fed back so the model can continue. Rare today:
        # every current skill returns terminal speech.
        return [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {"type": "function", "function": {"name": call.name, "arguments": call.arguments}}
                ],
            },
            {"role": "tool", "content": json.dumps(result.data or {"ok": result.success})},
        ]
