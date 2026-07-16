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
import time
from dataclasses import dataclass, field

from hearth.brain.base import BrainResult, Message
from hearth.brain.errors import BrainError
from hearth.brain.router import Router
from hearth.events import EventSink, ToolActivity, null_sink
from hearth.memory.log import EventLog
from hearth.persona import restyle

logger = logging.getLogger(__name__)


@dataclass
class ReactRoundsMetrics:
    """Aggregate token/duration metrics across every `brain.complete()` call
    made by one `run_react_rounds` invocation (FTHR-013). `round_count` and
    `call_count` are the same number here -- each ReAct round is exactly one
    LLM call -- but are named for what the per-turn summary reports."""

    round_count: int = 0
    call_count: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    duration_s: float = 0.0
    # FTHR-014: calls that raised `BrainError` or timed out. Included in
    # `call_count`/`duration_s`, excluded from `prompt_tokens`/
    # `completion_tokens` (they produced no completion).
    failed_count: int = 0


@dataclass
class ReactRoundsResult:
    result: BrainResult
    metrics: ReactRoundsMetrics = field(default_factory=ReactRoundsMetrics)


def _log_call_metrics(result: BrainResult, round_no: int) -> None:
    try:
        thinking = result.reasoning_tokens if result.reasoning_tokens is not None else "n/a"
        if result.duration_s and result.duration_s > 0 and result.completion_tokens is not None:
            tokens_per_s = f"{result.completion_tokens / result.duration_s:.1f}"
        else:
            tokens_per_s = "n/a"
        duration_str = f"{result.duration_s:.1f}s" if result.duration_s is not None else "n/a"
        logger.info(
            "llm call tier=%s model=%s round=%d in=%s out=%s thinking=%s duration_s=%s tok/s=%s",
            result.tier,
            result.model,
            round_no,
            result.prompt_tokens,
            result.completion_tokens,
            thinking,
            duration_str,
            tokens_per_s,
            extra={"category": "metrics"},
        )
    except Exception:  # never let logging break a turn (AC-5)
        pass


def _log_failed_call_marker(tier: str, round_no: int, reason: str, elapsed: float) -> None:
    """FTHR-014 AC-2: a FAILED marker for a `brain.complete()` call that
    raised `BrainError`. Logs `.reason` only -- `.detail` may carry raw HTTP
    body text and must never reach the log (see conventions.md)."""
    try:
        logger.warning(
            "llm call tier=%s round=%d FAILED reason=%s after=%.1fs",
            tier,
            round_no,
            reason,
            elapsed,
            extra={"category": "metrics"},
        )
    except Exception:  # never let logging break a turn (AC-5)
        pass


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
    metrics: ReactRoundsMetrics | None = None,
) -> ReactRoundsResult:
    """Thought -> Action -> Observation over `brain`, capped at `round_cap`
    tool rounds. Shared by the orchestrator's own turn and a nested brain
    consult -- no duplicated ReAct logic between the two call sites.

    `metrics` may be supplied by the caller (FTHR-014): a `BrainError` from
    `brain.complete()` is logged and re-raised unchanged, but the metrics
    mutation up to that point (including the failed call itself) happens
    in-place on this object, so a caller that passed it in can still read
    partial/failure metrics after catching the exception."""
    if metrics is None:
        metrics = ReactRoundsMetrics()

    def _record(res: BrainResult, round_no: int) -> None:
        metrics.round_count = round_no
        metrics.call_count += 1
        if res.prompt_tokens is not None:
            metrics.prompt_tokens += res.prompt_tokens
        if res.completion_tokens is not None:
            metrics.completion_tokens += res.completion_tokens
        if res.duration_s is not None:
            metrics.duration_s += res.duration_s
        _log_call_metrics(res, round_no)

    async def _complete(round_no: int) -> BrainResult:
        start = time.monotonic()
        try:
            return await brain.complete(messages, tools=tools)
        except BrainError as exc:
            elapsed = time.monotonic() - start
            metrics.round_count = round_no
            metrics.call_count += 1
            metrics.failed_count += 1
            metrics.duration_s += elapsed
            _log_failed_call_marker(getattr(brain, "tier", "?"), round_no, exc.reason, elapsed)
            raise

    result = await _complete(1)
    _record(result, 1)

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
            # The `end` emit lives in a finally so a timeout cancelling this
            # round (asyncio.wait_for at either call site) can't strand the
            # client on a dangling `start`. CancelledError is a BaseException,
            # so the inner `except Exception` doesn't swallow it: the pair is
            # balanced, then the cancellation keeps propagating.
            try:
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
            finally:
                await emit(ToolActivity(turn_id, "end", label))

            messages.append(
                Message(role="tool", content=observation, tool_call_id=call.id)
            )

        result = await _complete(round_count + 1)
        _record(result, round_count + 1)

    if result.tool_calls and not result.text:
        result.text = "I wasn't able to finish that within the allowed tool rounds."
    return ReactRoundsResult(result=result, metrics=metrics)


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

    def _log_turn_metrics(
        self,
        turn_number: int,
        own_metrics: ReactRoundsMetrics,
        nested_metrics: list[ReactRoundsMetrics],
    ) -> None:
        try:
            round_count = own_metrics.round_count + sum(m.round_count for m in nested_metrics)
            call_count = own_metrics.call_count + sum(m.call_count for m in nested_metrics)
            failed_count = own_metrics.failed_count + sum(
                m.failed_count for m in nested_metrics
            )
            prompt_tokens = own_metrics.prompt_tokens + sum(
                m.prompt_tokens for m in nested_metrics
            )
            completion_tokens = own_metrics.completion_tokens + sum(
                m.completion_tokens for m in nested_metrics
            )
            duration_s = own_metrics.duration_s + sum(m.duration_s for m in nested_metrics)
            tokens_per_s = f"{completion_tokens / duration_s:.1f}" if duration_s > 0 else "n/a"
            # FTHR-014 AC-4: a failed/timed-out call counts toward `calls`
            # and `duration_s` but not `in`/`out` -- the "(K failed)" suffix
            # only appears when at least one call failed (no "(0 failed)"
            # clutter on the happy path).
            calls_str = str(call_count) + (f" ({failed_count} failed)" if failed_count else "")
            logger.info(
                "turn summary turn=%d rounds=%d calls=%s in=%d out=%d duration_s=%.1fs tok/s=%s",
                turn_number,
                round_count,
                calls_str,
                prompt_tokens,
                completion_tokens,
                duration_s,
                tokens_per_s,
                extra={"category": "metrics"},
            )
        except Exception:  # never let logging break a turn (AC-5)
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

        # nested_metrics collects one `ReactRoundsMetrics` per consult_dispatch
        # call this turn, so the per-turn summary's totals include whatever
        # happened inside a nested consult_brain invocation (FTHR-013).
        nested_metrics: list[ReactRoundsMetrics] = []

        # Closure over this turn's session_id/turn_id/emit: `run_react_rounds`
        # fixes dispatch to `(name, args) -> str`, and binding per-turn context
        # here (not on self) keeps concurrent turns on the shared Loop from
        # leaking consult events into each other's session/sink.
        async def consult_dispatch(name: str, args: dict) -> str:
            findings = await self._consult(session_id, turn_id, args["query"], emit)
            nested_metrics.append(
                getattr(self._consult, "last_metrics", None) or ReactRoundsMetrics()
            )
            return findings

        def label_for(name: str) -> str:
            spec = next((s for s in (tools or []) if s.name == name), None)
            return spec.label if spec else name

        own_metrics = ReactRoundsMetrics()
        turn_start = time.monotonic()
        try:
            react_run = await asyncio.wait_for(
                run_react_rounds(
                    brain=selection.brain,
                    messages=messages,
                    tools=tools,
                    dispatch=consult_dispatch,
                    round_cap=self._config.agent.max_consult_rounds,
                    log=self._log,
                    session_id=session_id,
                    turn_id=turn_id,
                    emit=emit,
                    label_for=label_for,
                    metrics=own_metrics,
                ),
                timeout=self._config.agent.turn_timeout_s,
            )
            own_metrics = react_run.metrics
            answer_text = react_run.result.text or ""
        except asyncio.TimeoutError:
            # FTHR-014 AC-3/AC-4: log a timeout marker and count it as one
            # failed call toward the turn's call count/wall time. `own_metrics`
            # already reflects any rounds that completed before cancellation
            # (mutated in place by `run_react_rounds`); this adds the timed-
            # out attempt itself.
            elapsed = time.monotonic() - turn_start
            own_metrics.call_count += 1
            own_metrics.failed_count += 1
            own_metrics.duration_s += elapsed
            try:
                logger.warning(
                    "turn timeout tier=%s after=%.1fs",
                    selection.tier,
                    elapsed,
                    extra={"category": "metrics"},
                )
            except Exception:  # never let logging break a turn (AC-5)
                pass
            answer_text = "That took too long — here's what I have so far."

        answer = await restyle(answer_text, ctx=None)

        turn_number = sum(1 for e in turn_events if e.type == "final_answer") + 1
        self._log_turn_metrics(turn_number, own_metrics, nested_metrics)

        self._log.append(session_id, turn_id, "final_answer", "brain", {"text": answer})
        self._append_transcript(session_id, f"answer: {answer}")
        return answer
