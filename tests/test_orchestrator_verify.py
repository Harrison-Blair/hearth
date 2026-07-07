"""Verify-loop behavior in the orchestrator (docs §4 / §8).

Covers: filler speaks only on reject (pre+post); on_say barge aborts the turn;
best_draft spoken on TimeoutError else general fallback; a verify-reject consumes
a max_tool_rounds iteration; a verify-rejected same-tool re-pick does NOT count
toward _TOOL_REPEAT_CAP; the per-stage max_verify_rounds sub-cap stops re-looping;
verify.enabled=False is byte-identical to today; on_say=None and
spoken_feedback=False never speak a filler.
"""

import asyncio
import json

from assistant.core.config import VerifyConfig
from assistant.core.events import SkillResult, ToolCall
from assistant.core.orchestrator import Orchestrator
from assistant.llm.base import ChatResponse
from assistant.skills.base import Skill, SkillRegistry


# ---- test skills ------------------------------------------------------------


class EchoSkill(Skill):
    name = "echo"
    intents = {"echo"}
    tool_specs = {
        "echo": {
            "description": "echo text back",
            "parameters": {"type": "object", "properties": {"text": {"type": "string"}}},
        }
    }

    def __init__(self, speech="echoed"):
        self._speech = speech
        self.calls = 0
        self.received = None

    async def handle(self, cmd, intent):
        self.calls += 1
        self.received = intent
        return SkillResult(speech=self._speech)


class OtherSkill(Skill):
    name = "other"
    intents = {"other"}
    tool_specs = {
        "other": {
            "description": "the other tool",
            "parameters": {"type": "object", "properties": {"q": {"type": "string"}}},
        }
    }

    def __init__(self):
        self.calls = 0
        self.received = None

    async def handle(self, cmd, intent):
        self.calls += 1
        self.received = intent
        return SkillResult(speech="othered", data={"q": intent.slots.get("q")})


class FallbackSkill(Skill):
    name = "general"
    intents = {"general"}

    def __init__(self, speech="general answer"):
        self.calls = 0
        self._speech = speech

    def tools(self):
        return []

    async def handle(self, cmd, intent):
        self.calls += 1
        return SkillResult(speech=self._speech)


# ---- scriptable LLM (chat_tools=decide, complete=verify) --------------------


class ScriptedLLM:
    """Queued chat_tools (one per _decide) and complete (one per verify) responses.

    Use tool_mode="native" so _decide never falls back to the JSON path (which
    also calls complete); then complete is reached only by the verify call."""

    def __init__(self, *, tool_responses=None, complete_responses=None):
        self._tool_responses = list(tool_responses or [])
        self._complete_responses = list(complete_responses or [])
        self.chat_tools_calls = 0
        self.complete_calls = 0
        self.tool_messages: list[list[dict]] = []  # messages per _decide call
        self.complete_prompts: list[str] = []  # prompt per verify call

    async def chat_tools(self, messages, *, system=None, tools=None, label=""):
        self.chat_tools_calls += 1
        self.tool_messages.append([dict(m) for m in messages])
        return self._tool_responses.pop(0) if self._tool_responses else ChatResponse()

    async def complete(self, prompt, *, system=None, json=False, label=""):  # noqa: A002
        self.complete_calls += 1
        self.complete_prompts.append(prompt)
        return self._complete_responses.pop(0)

    async def chat(self, messages, *, system=None, label=""):
        raise AssertionError("orchestrator should not call chat()")

    async def health(self):
        return True


class SayRecorder:
    """An on_say channel that records spoken fillers (and their voiced flag) and
    can fake a barge-in."""

    def __init__(self, barged=False):
        self.spoken: list[str] = []
        self.voiced: list[bool] = []
        self._barged = barged

    async def __call__(self, text: str, *, voiced: bool = False) -> bool:
        self.spoken.append(text)
        self.voiced.append(voiced)
        return self._barged


def _verdict(decision: str, **extra) -> str:
    return json.dumps({"decision": decision, **extra})


def _reg(*skills, default) -> SkillRegistry:
    reg = SkillRegistry()
    for skill in skills:
        reg.register(skill)
    reg.register(default, default=True)
    return reg


def _echo_call() -> ChatResponse:
    return ChatResponse(tool_calls=[ToolCall("echo", {"text": "hi"})])


def _other_call() -> ChatResponse:
    return ChatResponse(tool_calls=[ToolCall("other", {"q": "x"})])


# ---- tests ------------------------------------------------------------------


async def test_verify_disabled_is_byte_identical():
    echo = EchoSkill()
    reg = _reg(echo, default=FallbackSkill())
    llm = ScriptedLLM(tool_responses=[_echo_call()])
    rec = SayRecorder()
    orch = Orchestrator(
        llm, reg, tool_mode="native",
        verify=VerifyConfig(enabled=False), persona_suffix="P",
    )
    result, skill = await orch.handle("echo hi", [], spoken=True, on_say=rec)
    assert result.speech == "echoed"
    assert skill is echo
    assert llm.complete_calls == 0  # no verify calls
    assert rec.spoken == []  # no filler
    assert echo.calls == 1


async def test_pre_and_post_approve_proceeds_silently():
    echo = EchoSkill()
    reg = _reg(echo, default=FallbackSkill())
    llm = ScriptedLLM(
        tool_responses=[_echo_call()],
        complete_responses=[_verdict("approve"), _verdict("approve")],  # pre, post
    )
    rec = SayRecorder()
    orch = Orchestrator(llm, reg, tool_mode="native", verify=VerifyConfig())
    result, skill = await orch.handle("echo hi", [], spoken=True, on_say=rec)
    assert result.speech == "echoed"
    assert llm.complete_calls == 2  # pre + post
    assert rec.spoken == []  # approve stays silent


async def test_pre_reject_speaks_filler_and_redecides():
    echo = EchoSkill()
    reg = _reg(echo, default=FallbackSkill())
    llm = ScriptedLLM(
        tool_responses=[_echo_call(), _echo_call()],  # decide0, re-decide1
        complete_responses=[
            _verdict("reject", feedback="let me double check that"),
            _verdict("approve"),  # pre1
            _verdict("approve"),  # post1
        ],
    )
    rec = SayRecorder()
    orch = Orchestrator(llm, reg, tool_mode="native", verify=VerifyConfig())
    result, skill = await orch.handle("echo hi", [], spoken=True, on_say=rec)
    assert result.speech == "echoed"
    assert rec.spoken == ["let me double check that"]  # only the reject filler
    assert rec.voiced == [True]  # verify's feedback is already persona-flavored
    assert echo.calls == 1  # skill ran once (on the re-decide)
    assert llm.chat_tools_calls == 2


async def test_post_reject_speaks_filler_and_redecides():
    echo = EchoSkill()
    reg = _reg(echo, default=FallbackSkill())
    llm = ScriptedLLM(
        tool_responses=[_echo_call(), _echo_call()],
        complete_responses=[
            _verdict("approve"),  # pre0
            _verdict("reject", feedback="that's not right"),  # post0
            _verdict("approve"),  # pre1
            _verdict("approve"),  # post1
        ],
    )
    rec = SayRecorder()
    orch = Orchestrator(llm, reg, tool_mode="native", verify=VerifyConfig())
    result, skill = await orch.handle("echo hi", [], spoken=True, on_say=rec)
    assert result.speech == "echoed"
    assert rec.spoken == ["that's not right"]
    assert rec.voiced == [True]  # verify's feedback is already persona-flavored
    assert echo.calls == 2  # ran on iter0 and the re-decide


async def test_filler_silent_on_approve_and_rewrite():
    # Neither approve nor rewrite speaks a filler — only reject does.
    echo = EchoSkill()
    reg = _reg(echo, default=FallbackSkill())
    llm = ScriptedLLM(
        tool_responses=[_echo_call()],
        complete_responses=[
            _verdict("approve"),  # pre
            _verdict("rewrite", rewritten_speech="corrected answer"),  # post
        ],
    )
    rec = SayRecorder()
    orch = Orchestrator(llm, reg, tool_mode="native", verify=VerifyConfig())
    result, skill = await orch.handle("echo hi", [], spoken=True, on_say=rec)
    assert result.speech == "corrected answer"
    assert rec.spoken == []  # rewrite is a silent self-correction
    assert result.voiced  # rewritten_speech is already persona-flavored


async def test_pre_rewrite_replaces_the_pick():
    echo = EchoSkill()
    other = OtherSkill()
    reg = _reg(echo, other, default=FallbackSkill())
    llm = ScriptedLLM(
        tool_responses=[_echo_call()],  # model picks echo
        complete_responses=[
            _verdict("rewrite", rewritten_tool="other", rewritten_arguments={"q": "fixed"}),
            _verdict("approve"),  # post
        ],
    )
    rec = SayRecorder()
    orch = Orchestrator(llm, reg, tool_mode="native", verify=VerifyConfig())
    result, skill = await orch.handle("do a thing", [], spoken=True, on_say=rec)
    assert skill is other  # the rewritten tool ran, not echo
    assert other.received.slots == {"q": "fixed"}
    assert result.speech == "othered"
    assert echo.calls == 0


async def test_post_rewrite_replaces_speech():
    echo = EchoSkill(speech="wrong answer")
    reg = _reg(echo, default=FallbackSkill())
    llm = ScriptedLLM(
        tool_responses=[_echo_call()],
        complete_responses=[
            _verdict("approve"),  # pre
            _verdict("rewrite", rewritten_speech="corrected answer"),  # post
        ],
    )
    orch = Orchestrator(llm, reg, tool_mode="native", verify=VerifyConfig())
    result, _ = await orch.handle("echo hi", [], spoken=True, on_say=SayRecorder())
    assert result.speech == "corrected answer"
    assert result.voiced  # rewritten_speech is already persona-flavored


async def test_pre_reject_barge_aborts_turn():
    echo = EchoSkill()
    reg = _reg(echo, default=FallbackSkill())
    llm = ScriptedLLM(
        tool_responses=[_echo_call()],
        complete_responses=[_verdict("reject", feedback="hold on")],
    )
    rec = SayRecorder(barged=True)
    orch = Orchestrator(llm, reg, tool_mode="native", verify=VerifyConfig())
    result, skill = await orch.handle("echo hi", [], spoken=True, on_say=rec)
    assert rec.spoken == ["hold on"]
    assert rec.voiced == [True]  # verify's feedback is already persona-flavored
    assert result.speech == ""  # aborted: nothing more spoken
    assert skill is None
    assert echo.calls == 0  # skill never ran


async def test_best_draft_spoken_on_timeout():
    # The skill runs and produces a draft; the post-verify call blows the turn
    # budget. The validated draft is spoken instead of discarding it.
    echo = EchoSkill(speech="the real answer")

    class SlowPostLLM:
        def __init__(self):
            self.chat_tools_calls = 0
            self.complete_calls = 0

        async def chat_tools(self, messages, *, system=None, tools=None, label=""):
            self.chat_tools_calls += 1
            return _echo_call()

        async def complete(self, prompt, *, system=None, json=False, label=""):  # noqa: A002
            self.complete_calls += 1
            if self.complete_calls == 1:
                return _verdict("approve")  # pre-verify: fast
            await asyncio.sleep(0.5)  # post-verify: blow the tiny budget
            return _verdict("approve")

        async def chat(self, *a, **k):
            raise AssertionError

        async def health(self):
            return True

    reg = _reg(echo, default=FallbackSkill())
    orch = Orchestrator(
        SlowPostLLM(), reg, tool_mode="native",
        turn_timeout_s=0.05, verify=VerifyConfig(),
    )
    result, skill = await orch.handle("echo hi", [], spoken=True, on_say=SayRecorder())
    assert result.speech == "the real answer"  # best draft, not the fallback
    assert skill is None
    assert echo.calls == 1


async def test_no_draft_on_timeout_falls_back_to_general():
    # The pre-verify call blows the budget before any skill runs -> no draft ->
    # today's general fallback.

    class SlowPreLLM:
        def __init__(self):
            self.chat_tools_calls = 0

        async def chat_tools(self, messages, *, system=None, tools=None, label=""):
            self.chat_tools_calls += 1
            return _echo_call()

        async def complete(self, prompt, *, system=None, json=False, label=""):  # noqa: A002
            await asyncio.sleep(0.5)  # pre-verify blows the budget
            return _verdict("approve")

        async def chat(self, *a, **k):
            raise AssertionError

        async def health(self):
            return True

    echo = EchoSkill()
    fallback = FallbackSkill(speech="general fallback")
    reg = _reg(echo, default=fallback)
    orch = Orchestrator(
        SlowPreLLM(), reg, tool_mode="native",
        turn_timeout_s=0.05, verify=VerifyConfig(),
    )
    result, skill = await orch.handle("echo hi", [], spoken=True, on_say=SayRecorder())
    assert result.speech == "general fallback"
    assert skill is fallback
    assert echo.calls == 0  # never got past pre-verify


async def test_verify_reject_consumes_a_max_tool_rounds_iteration():
    # max_tool_rounds=1: a pre-reject uses the only iteration; there's no room to
    # re-decide, so the turn falls back (the skill never runs).
    echo = EchoSkill()
    fallback = FallbackSkill()
    reg = _reg(echo, default=fallback)
    llm = ScriptedLLM(
        tool_responses=[_echo_call()],
        complete_responses=[_verdict("reject", feedback="nope")],
    )
    orch = Orchestrator(
        llm, reg, tool_mode="native", max_tool_rounds=1, verify=VerifyConfig(),
    )
    result, skill = await orch.handle("echo hi", [], spoken=True, on_say=SayRecorder())
    assert skill is fallback
    assert echo.calls == 0
    assert llm.chat_tools_calls == 1  # only one decide


async def test_verify_rejected_same_tool_repick_does_not_count_to_repeat_cap():
    # Without the §4c rule, three same-tool skill runs would trip _TOOL_REPEAT_CAP
    # (cap=2) on the third and break to fallback. With the rule, verify-guided
    # re-picks don't count, so all three runs land and the skill's answer returns.
    echo = EchoSkill(speech="echoed")
    fallback = FallbackSkill()
    reg = _reg(echo, default=fallback)
    # iter0: pre-reject; iter1: pre-approve + post-reject; iter2: pre-approve +
    # post-reject; iter3: pre-approve + post-approve.
    llm = ScriptedLLM(
        tool_responses=[_echo_call() for _ in range(4)],
        complete_responses=[
            _verdict("reject", feedback="retry"),       # pre0
            _verdict("approve"), _verdict("reject", feedback="retry"),  # pre1, post1
            _verdict("approve"), _verdict("reject", feedback="retry"),  # pre2, post2
            _verdict("approve"), _verdict("approve"),   # pre3, post3
        ],
    )
    orch = Orchestrator(
        llm, reg, tool_mode="native",
        max_tool_rounds=4, verify=VerifyConfig(),
    )
    result, skill = await orch.handle("echo hi", [], spoken=True, on_say=SayRecorder())
    assert result.speech == "echoed"  # NOT the fallback — the cap never tripped
    assert skill is echo
    assert echo.calls == 3  # ran on iter1, iter2, iter3
    assert llm.chat_tools_calls == 4


async def test_per_stage_max_verify_rounds_subcap_stops_relooping():
    # max_verify_rounds=1: only one pre-reject is allowed; the second pre-verify
    # is skipped (proceed with the pick) rather than re-looping.
    echo = EchoSkill()
    fallback = FallbackSkill()
    reg = _reg(echo, default=fallback)
    llm = ScriptedLLM(
        tool_responses=[_echo_call(), _echo_call()],
        complete_responses=[
            _verdict("reject", feedback="retry"),  # pre0 (the one allowed reject)
            # pre1 is SKIPPED (pre_rejects=1 not < 1) — no complete call here
            _verdict("approve"),  # post1
        ],
    )
    orch = Orchestrator(
        llm, reg, tool_mode="native",
        verify=VerifyConfig(max_verify_rounds=1),
    )
    result, skill = await orch.handle("echo hi", [], spoken=True, on_say=SayRecorder())
    assert result.speech == "echoed"
    assert skill is echo
    assert echo.calls == 1
    assert llm.complete_calls == 2  # pre0 + post1 only — pre1 was skipped


async def test_on_say_none_no_filler_no_crash():
    echo = EchoSkill()
    reg = _reg(echo, default=FallbackSkill())
    llm = ScriptedLLM(
        tool_responses=[_echo_call(), _echo_call()],
        complete_responses=[
            _verdict("reject", feedback="let me check"),  # pre0 reject
            _verdict("approve"),  # pre1
            _verdict("approve"),  # post1
        ],
    )
    orch = Orchestrator(llm, reg, tool_mode="native", verify=VerifyConfig())
    # on_say not passed -> defaults to None -> reject must not crash, no filler.
    result, skill = await orch.handle("echo hi", [], spoken=True)
    assert result.speech == "echoed"
    assert echo.calls == 1


async def test_spoken_feedback_false_no_filler_on_reject():
    echo = EchoSkill()
    reg = _reg(echo, default=FallbackSkill())
    llm = ScriptedLLM(
        tool_responses=[_echo_call(), _echo_call()],
        complete_responses=[
            _verdict("reject", feedback="let me check"),  # pre0 reject
            _verdict("approve"),  # pre1
            _verdict("approve"),  # post1
        ],
    )
    rec = SayRecorder()
    orch = Orchestrator(
        llm, reg, tool_mode="native", verify=VerifyConfig(spoken_feedback=False),
    )
    result, skill = await orch.handle("echo hi", [], spoken=True, on_say=rec)
    assert result.speech == "echoed"
    assert rec.spoken == []  # feedback off -> filler never spoken


async def test_verify_failopen_treats_bad_verdict_as_approve():
    # A malformed verify response (missing decision) -> None -> approve -> proceed.
    echo = EchoSkill()
    reg = _reg(echo, default=FallbackSkill())
    llm = ScriptedLLM(
        tool_responses=[_echo_call()],
        complete_responses=[
            json.dumps({"rewritten_tool": "echo"}),  # no decision -> None
            "not even json",  # post -> None
        ],
    )
    orch = Orchestrator(llm, reg, tool_mode="native", verify=VerifyConfig())
    result, skill = await orch.handle("echo hi", [], spoken=True, on_say=SayRecorder())
    assert result.speech == "echoed"  # fail-open: both verifies treated as approve
    assert skill is echo


async def test_pre_reject_reason_feeds_the_redecide():
    # The verifier's neutral reason must reach the model's next decide as a user
    # message naming the rejected tool, the reason, and the original request.
    echo = EchoSkill()
    other = OtherSkill()
    reg = _reg(echo, other, default=FallbackSkill())
    llm = ScriptedLLM(
        tool_responses=[_echo_call(), _other_call()],
        complete_responses=[
            _verdict("reject", reason="use the other tool instead", feedback="hold on"),
            _verdict("approve"),  # pre1
            _verdict("approve"),  # post1
        ],
    )
    orch = Orchestrator(llm, reg, tool_mode="native", verify=VerifyConfig())
    result, skill = await orch.handle("echo hi", [], spoken=True, on_say=SayRecorder())
    assert skill is other
    first, second = llm.tool_messages
    assert len(second) == len(first) + 1  # exactly one injected message
    injected = second[-1]
    assert injected["role"] == "user"
    assert '"echo"' in injected["content"]  # the rejected tool
    assert "use the other tool instead" in injected["content"]  # the reason
    assert "echo hi" in injected["content"]  # the original request


async def test_post_reject_reason_and_draft_feed_the_redecide():
    echo = EchoSkill(speech="wrong draft")
    other = OtherSkill()
    reg = _reg(echo, other, default=FallbackSkill())
    llm = ScriptedLLM(
        tool_responses=[_echo_call(), _other_call()],
        complete_responses=[
            _verdict("approve"),  # pre0
            _verdict("reject", reason="the answer ignored the question"),  # post0
            _verdict("approve"),  # pre1
            _verdict("approve"),  # post1
        ],
    )
    orch = Orchestrator(llm, reg, tool_mode="native", verify=VerifyConfig())
    result, skill = await orch.handle("echo hi", [], spoken=True, on_say=SayRecorder())
    assert skill is other
    injected = llm.tool_messages[1][-1]
    assert injected["role"] == "user"
    assert "wrong draft" in injected["content"]  # the rejected draft
    assert "the answer ignored the question" in injected["content"]
    assert "echo hi" in injected["content"]


async def test_pre_reject_without_reason_falls_back_to_feedback_text():
    echo = EchoSkill()
    reg = _reg(echo, default=FallbackSkill())
    llm = ScriptedLLM(
        tool_responses=[_echo_call(), _echo_call()],
        complete_responses=[
            _verdict("reject", feedback="that tool cannot answer this"),
            _verdict("approve"),  # pre1
            _verdict("approve"),  # post1
        ],
    )
    orch = Orchestrator(llm, reg, tool_mode="native", verify=VerifyConfig())
    await orch.handle("echo hi", [], spoken=True, on_say=SayRecorder())
    injected = llm.tool_messages[1][-1]
    assert injected["role"] == "user"
    assert "that tool cannot answer this" in injected["content"]


async def test_extra_tool_calls_surface_as_alternatives_to_pre_verify():
    # The model proposes two calls; only the first is considered, but the second
    # must appear in the pre-verify prompt so the verifier can rewrite to it.
    echo = EchoSkill()
    other = OtherSkill()
    reg = _reg(echo, other, default=FallbackSkill())
    llm = ScriptedLLM(
        tool_responses=[
            ChatResponse(tool_calls=[ToolCall("echo", {"text": "hi"}), ToolCall("other", {"q": "x"})])
        ],
        complete_responses=[
            _verdict("rewrite", rewritten_tool="other", rewritten_arguments={"q": "x"}),
            _verdict("approve"),  # post
        ],
    )
    orch = Orchestrator(llm, reg, tool_mode="native", verify=VerifyConfig())
    result, skill = await orch.handle("do a thing", [], spoken=True, on_say=SayRecorder())
    pre_prompt = llm.complete_prompts[0]
    assert "Other tools the model also proposed" in pre_prompt
    assert '"other"' in pre_prompt
    assert skill is other  # the verifier's rewrite to the alternative ran
    assert other.calls == 1
    assert echo.calls == 0


async def test_alternatives_ride_the_pre_reject_feedback():
    echo = EchoSkill()
    other = OtherSkill()
    reg = _reg(echo, other, default=FallbackSkill())
    llm = ScriptedLLM(
        tool_responses=[
            ChatResponse(tool_calls=[ToolCall("echo", {"text": "hi"}), ToolCall("other", {"q": "x"})]),
            _other_call(),
        ],
        complete_responses=[
            _verdict("reject", reason="echo cannot answer this"),
            _verdict("approve"),  # pre1
            _verdict("approve"),  # post1
        ],
    )
    orch = Orchestrator(llm, reg, tool_mode="native", verify=VerifyConfig())
    await orch.handle("do a thing", [], spoken=True, on_say=SayRecorder())
    injected = llm.tool_messages[1][-1]
    assert "You also proposed" in injected["content"]
    assert '"other"' in injected["content"]
