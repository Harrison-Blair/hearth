"""Tool-calling orchestrator.

Turns a transcript into a spoken result: the model picks a tool (a skill intent)
and fills its arguments, or answers directly from general knowledge. The tool
arguments populate ``Intent.slots`` for free.

The tool decision is model-agnostic (``tool_mode``): a native Ollama tool-calling
path with a prompt-coerced JSON fallback — native -> JSON -> (LLM offline)
default-intent general fallback, which itself speaks a clean "couldn't reach my
language model" message.

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
from collections.abc import Awaitable, Callable

from assistant.core.config import VerifyConfig
from assistant.core.events import Command, Intent, SkillResult, ToolCall, Turn
from assistant.core.verify import Verdict, verify as _verify_turn
from assistant.llm.base import ChatResponse, LLMProvider
from assistant.skills.base import Skill, SkillRegistry

log = logging.getLogger(__name__)

# Appended to the tool-decision system prompt only (never GeneralSkill's answer
# prompt). Hard-coded like verify.py's judgment prompt, not a config tunable.
_ROUTING_GUIDANCE = (
    "When picking a tool: questions about schedules, scores, news, prices, or "
    "anything happening now or recently need web_search even if the user does not "
    "say 'search'; the date/time tools only answer what the date or time IS. "
    "Answer stable general knowledge directly without a tool."
)


class Orchestrator:
    # Break to the general fallback if the model calls one tool name more than this
    # many times in a turn — a verifier stall re-calling the same tool otherwise
    # burns the whole round budget on a loop.
    _TOOL_REPEAT_CAP = 2

    def __init__(
        self,
        llm: LLMProvider,
        registry: SkillRegistry,
        *,
        tool_mode: str = "auto",
        max_tool_rounds: int = 3,
        system_prompt: str = "",
        default_intent: str = "general",
        turn_timeout_s: float = 20.0,
        delegate_direct_answers: bool = False,
        verify: VerifyConfig | None = None,
        persona_suffix: str = "",
    ) -> None:
        self._llm = llm
        self._registry = registry
        self._tool_mode = tool_mode
        self._max_rounds = max(1, max_tool_rounds)
        self._system = " ".join(p for p in (system_prompt.strip(), _ROUTING_GUIDANCE) if p)
        # When set, a no-tool direct answer is regenerated through the default
        # skill (which carries the persona voice) instead of spoken verbatim from
        # the persona-free tool-decision call. Off = byte-identical passthrough.
        self._delegate_direct = delegate_direct_answers
        self._default_intent = default_intent
        self._turn_timeout = turn_timeout_s
        self._tools = registry.tool_schemas()
        self._tool_names = {t["function"]["name"] for t in self._tools}
        # Follow-up verification loop (None = today's single-pass behavior). The
        # persona rides only the verify call's spoken outputs (feedback,
        # rewritten_speech), never the verdict — see core/verify.py.
        self._verify_cfg = verify
        self._persona_suffix = persona_suffix

    async def handle(
        self,
        text: str,
        history: list[Turn],
        *,
        spoken: bool,
        on_say: Callable[[str], Awaitable[bool]] | None = None,
    ) -> tuple[SkillResult | None, Skill | None]:
        """Route one utterance to a spoken result. Returns ``(result, skill)`` where
        ``skill`` is the handler (so the caller can route a follow-up to it), or
        ``(None, None)`` when nothing could handle it. Skill exceptions propagate to
        the caller; LLM failures degrade internally to the general fallback.

        When a ``VerifyConfig`` is wired in, a follow-up verify loop reviews the
        model's tool pick (pre) and its drafted answer (post) before speech: a
        ``reject`` speaks a filler via ``on_say`` (the pipeline's ``_speak``, which
        holds the audio arbiter for the whole turn) and re-decides, consuming a
        ``max_tool_rounds`` iteration; a ``rewrite`` silently corrects the pick or
        the answer. ``on_say=None`` (or verify off) is today's single-pass behavior.
        """
        messages = self._messages(text, history)
        history_dicts = [{"role": t.role, "content": t.content} for t in history]
        tool_counts: dict[str, int] = {}
        pre_rejects = 0
        post_rejects = 0
        # A verify-rejected re-pick is verify-guided, not a model stall, so it must
        # NOT count toward _TOOL_REPEAT_CAP (§4c). This flag marks the pick that
        # immediately follows a verify-reject so its tool_counts increment is skipped.
        prev_verify_reject = False
        best_draft: str | None = None
        verify_on = self._verify_cfg is not None and self._verify_cfg.enabled
        # 1. Tool-calling loop, bounded by a whole-turn budget so a stuck model
        #    can't hold the mic; on timeout we speak the best validated draft (or
        #    degrade to the general fallback when there is none).
        try:
            async with asyncio.timeout(self._turn_timeout):
                for _ in range(self._max_rounds):
                    try:
                        resp = await self._decide(messages)
                    except Exception as exc:  # noqa: BLE001 - LLM down -> answer offline-gracefully
                        log.warning("Tool decision failed: %s; answering from general knowledge", exc)
                        return await self._fall_back_turn(text, history, spoken=spoken)

                    if resp.tool_calls:
                        call = resp.tool_calls[0]
                        if call.name not in self._tool_names:
                            log.warning("Model called unknown tool %r; falling back", call.name)
                            break
                        # Only one call executes per round (skill speech is terminal);
                        # the rest are surfaced to the pre-verifier as alternatives
                        # rather than silently dropped.
                        alternatives = [
                            {"tool": c.name, "arguments": dict(c.arguments)}
                            for c in resp.tool_calls[1:]
                            if c.name in self._tool_names and c.name != call.name
                        ]
                        if len(resp.tool_calls) > 1:
                            log.info(
                                "Model proposed %d tool calls; considering %r, alternatives: %s",
                                len(resp.tool_calls), call.name,
                                [a["tool"] for a in alternatives],
                            )

                        # PRE-verify: review the pick + args before the skill runs.
                        if (
                            verify_on
                            and self._verify_cfg.pre
                            and pre_rejects < self._verify_cfg.max_verify_rounds
                        ):
                            verdict = await _verify_turn(
                                "pre",
                                {
                                    "request": text,
                                    "history": history_dicts,
                                    "tool": call.name,
                                    "arguments": dict(call.arguments),
                                    "alternatives": alternatives,
                                },
                                llm=self._llm,
                                persona_suffix=self._persona_suffix,
                                spoken_feedback=self._verify_cfg.spoken_feedback,
                            )
                            if verdict is not None and verdict.decision == "reject":
                                pre_rejects += 1
                                prev_verify_reject = True
                                if await self._speak_filler(verdict, on_say):
                                    return SkillResult(speech=""), None  # barged: give the mic back
                                messages.append(
                                    self._reject_feedback(
                                        "pre", text, call, verdict, alternatives=alternatives
                                    )
                                )
                                continue  # re-decide (consumes a max_tool_rounds iteration)
                            if (
                                verdict is not None
                                and verdict.decision == "rewrite"
                                and verdict.rewritten_tool in self._tool_names
                            ):
                                call = ToolCall(
                                    verdict.rewritten_tool, verdict.rewritten_arguments
                                )
                            # approve (or fail-open None) -> proceed with the pick

                        # _TOOL_REPEAT_CAP guards unguided model stalls. A pick that
                        # follows a verify-reject is guided, so it doesn't count.
                        if not prev_verify_reject:
                            tool_counts[call.name] = tool_counts.get(call.name, 0) + 1
                            if tool_counts[call.name] > self._TOOL_REPEAT_CAP:
                                log.warning(
                                    "Model re-called %r past the repeat cap; falling back",
                                    call.name,
                                )
                                break
                        prev_verify_reject = False
                        log.info(
                            "Tool call: %s", call.name,
                            extra={"data": {
                                "kind": "route.tool",
                                "tool": call.name,
                                "arguments": dict(call.arguments),
                            }},
                        )
                        skill = self._registry.get(call.name)
                        intent = Intent(type=call.name, slots=dict(call.arguments), raw_text=text)
                        result = await skill.handle(
                            Command(text, spoken=spoken, history=history), intent
                        )
                        if not result.speech:
                            messages.extend(self._tool_feedback(call, result))
                            continue
                        best_draft = result.speech

                        # POST-verify: review the drafted answer before speech.
                        if (
                            verify_on
                            and self._verify_cfg.post
                            and post_rejects < self._verify_cfg.max_verify_rounds
                        ):
                            verdict = await _verify_turn(
                                "post",
                                {
                                    "request": text,
                                    "history": history_dicts,
                                    "tool": call.name,
                                    "arguments": dict(call.arguments),
                                    "result": result.data
                                    if result.data is not None
                                    else {"success": result.success},
                                    "draft_speech": result.speech,
                                },
                                llm=self._llm,
                                persona_suffix=self._persona_suffix,
                                spoken_feedback=self._verify_cfg.spoken_feedback,
                            )
                            if verdict is not None and verdict.decision == "reject":
                                post_rejects += 1
                                prev_verify_reject = True
                                if await self._speak_filler(verdict, on_say):
                                    return SkillResult(speech=""), None  # barged
                                messages.append(
                                    self._reject_feedback(
                                        "post", text, call, verdict, draft=result.speech
                                    )
                                )
                                continue  # re-decide (skill already ran; side effect stands)
                            if (
                                verdict is not None
                                and verdict.decision == "rewrite"
                                and verdict.rewritten_speech
                            ):
                                result = SkillResult(
                                    speech=verdict.rewritten_speech,
                                    data=result.data,
                                    success=result.success,
                                    expects_reply=result.expects_reply,
                                )
                                best_draft = result.speech
                            # approve (or fail-open None / empty rewrite) -> speak result.speech

                        self._log_turn(
                            text, history, spoken=spoken, route="tool",
                            intent=intent, result=result, skill=skill,
                        )
                        return result, skill

                    if resp.content:
                        log.info("Direct answer (no tool)")
                        if self._delegate_direct:
                            # Re-voice the model's own answer through the persona-bearing
                            # default skill; the tool-decision call stays persona-free.
                            return await self._fall_back_turn(
                                text, history, spoken=spoken, draft=resp.content
                            )
                        result = SkillResult(speech=resp.content)
                        self._log_turn(
                            text, history, spoken=spoken, route="direct",
                            result=result, skill=None,
                        )
                        return result, None
                    break
        except TimeoutError:
            log.warning(
                "Turn exceeded %.1fs budget; %s", self._turn_timeout,
                "speaking best draft" if best_draft else "answering from general knowledge",
            )
            if best_draft:
                result = SkillResult(speech=best_draft)
                self._log_turn(
                    text, history, spoken=spoken, route="timeout",
                    result=result, skill=None,
                )
                return result, None

        # 2. No tool chosen / rounds exhausted / timed out (no draft): answer from
        # general knowledge.
        return await self._fall_back_turn(text, history, spoken=spoken)

    async def _speak_filler(
        self, verdict: Verdict, on_say: Callable[[str], Awaitable[bool]] | None
    ) -> bool:
        """Speak a reject's filler via the mid-turn channel; return True if the user
        barged in (the caller aborts the turn). Silent when spoken feedback is off,
        the filler is empty, or no channel is wired (e.g. a non-pipeline caller)."""
        if not self._verify_cfg or not self._verify_cfg.spoken_feedback:
            return False
        if not verdict.feedback or on_say is None:
            return False
        return bool(await on_say(verdict.feedback))

    async def _fall_back_turn(
        self, text: str, history: list[Turn], *, spoken: bool, draft: str | None = None
    ) -> tuple[SkillResult | None, Skill | None]:
        result, skill = await self._dispatch(
            self._fallback(text, draft), text, history, spoken=spoken
        )
        self._log_turn(text, history, spoken=spoken, route="fallback", result=result, skill=skill)
        return result, skill

    def _log_turn(
        self,
        text: str,
        history: list[Turn],
        *,
        spoken: bool,
        route: str,
        result: SkillResult | None,
        skill: Skill | None,
        intent: Intent | None = None,
    ) -> None:
        # Console stays terse; the full turn record rides `data` into the JSONL file,
        # where the replay eval's extraction tool picks it up (tests/eval/extract.py).
        log.info(
            "Turn (%s): %s", route, skill.name if skill else "direct",
            extra={"data": {
                "kind": "turn",
                "text": text,
                "spoken": spoken,
                "history": [{"role": t.role, "content": t.content} for t in history],
                "route": route,
                "tool": intent.type if intent else None,
                "slots": dict(intent.slots) if intent else {},
                "skill": skill.name if skill else None,
                "speech": result.speech if result else "",
                "success": result.success if result else False,
                "expects_reply": result.expects_reply if result else False,
            }},
        )

    async def _dispatch(
        self, intent: Intent, text: str, history: list[Turn], *, spoken: bool
    ) -> tuple[SkillResult | None, Skill | None]:
        skill = self._registry.get(intent.type)
        if skill is None:
            return None, None
        result = await skill.handle(Command(text, spoken=spoken, history=history), intent)
        return result, skill

    def _fallback(self, text: str, draft: str | None = None) -> Intent:
        # A draft (the model's own direct answer) is restyled in persona rather than
        # re-derived; without one the general skill answers from general knowledge.
        slots = {"draft": draft} if draft else {}
        return Intent(type=self._default_intent, slots=slots, raw_text=text)

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
    def _reject_feedback(
        stage: str,
        text: str,
        call: ToolCall,
        verdict: Verdict,
        draft: str = "",
        alternatives: list[dict] | None = None,
    ) -> dict:
        # One user-role message (not an assistant+tool pair: a `tool` message is
        # malformed when the skill never ran, and _decide_json reads only the last
        # message's content) telling the model why its pick was rejected.
        reason = verdict.reason or verdict.feedback
        if stage == "pre":
            detail = (
                f'A verification step rejected calling the tool "{call.name}" with '
                f"arguments {json.dumps(call.arguments)}"
            )
        else:
            detail = (
                f'A verification step rejected the answer "{draft}" from the tool '
                f'"{call.name}" with arguments {json.dumps(call.arguments)}'
            )
        if reason:
            detail += f": {reason}"
        if alternatives:
            detail += f". You also proposed: {json.dumps(alternatives)}"
        return {
            "role": "user",
            "content": (
                f"{detail}. Do not repeat that choice — pick a different tool or "
                f'answer directly. My request: "{text}"'
            ),
        }

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
