import asyncio
import logging

from assistant.core import persona
from assistant.core.events import SkillResult, ToolCall, Turn
from assistant.core.orchestrator import Orchestrator
from assistant.llm.base import ChatResponse
from assistant.skills.base import Skill, SkillRegistry
from assistant.skills.update import UpdateSkill


class EchoSkill(Skill):
    name = "echo"
    intents = {"echo"}
    tool_specs = {
        "echo": {
            "description": "echo text",
            "parameters": {"type": "object", "properties": {"text": {"type": "string"}}},
        }
    }

    def __init__(self, speech="echoed"):
        self.received = None
        self._speech = speech

    async def handle(self, cmd, intent):
        self.received = intent
        return SkillResult(speech=self._speech)


class DataOnlySkill(Skill):
    """Returns no speech, forcing the tool loop to continue another round."""

    name = "lookup"
    intents = {"lookup"}

    def __init__(self):
        self.calls = 0

    async def handle(self, cmd, intent):
        self.calls += 1
        return SkillResult(speech="", data={"n": self.calls})


class FallbackSkill(Skill):
    name = "general"
    intents = {"general"}

    def __init__(self, speech="general answer"):
        self.calls = 0
        self.received = None
        self._speech = speech

    def tools(self):
        return []

    async def handle(self, cmd, intent):
        self.calls += 1
        self.received = intent
        return SkillResult(speech=self._speech)


class ScriptedLLM:
    """Serves queued chat_tools/complete responses and records call counts. An empty
    queue for a method that gets called is itself a failure signal (IndexError)."""

    def __init__(self, *, tool_responses=None, complete_responses=None, chat_tools_raises=False):
        self._tool_responses = list(tool_responses or [])
        self._complete_responses = list(complete_responses or [])
        self._chat_tools_raises = chat_tools_raises
        self.chat_tools_calls = 0
        self.complete_calls = 0

    async def chat_tools(self, messages, *, system=None, tools=None, label=""):
        self.chat_tools_calls += 1
        if self._chat_tools_raises:
            raise RuntimeError("native tools down")
        return self._tool_responses.pop(0) if self._tool_responses else ChatResponse()

    async def complete(self, prompt, *, system=None, json=False, label=""):  # noqa: A002
        self.complete_calls += 1
        return self._complete_responses.pop(0)

    async def chat(self, messages, *, system=None, label=""):
        raise AssertionError("orchestrator should not call chat()")

    async def health(self):
        return True


def _registry(*skills, default):
    reg = SkillRegistry()
    for skill in skills:
        reg.register(skill)
    reg.register(default, default=True)
    return reg


def _orch(llm, registry, **kw):
    return Orchestrator(llm, registry, **kw)


async def test_tool_call_dispatches_with_arguments_in_slots():
    echo = EchoSkill(speech="echoed hi")
    fallback = FallbackSkill()
    reg = _registry(echo, default=fallback)
    llm = ScriptedLLM(tool_responses=[ChatResponse(tool_calls=[ToolCall("echo", {"text": "hi"})])])

    result, skill = await _orch(llm, reg, tool_mode="native").handle(
        "please echo hi", [], spoken=True
    )

    assert result.speech == "echoed hi"
    assert skill is echo
    assert echo.received.type == "echo"
    assert echo.received.slots == {"text": "hi"}  # tool args populate Intent.slots
    assert llm.chat_tools_calls == 1
    assert fallback.calls == 0


async def test_typed_update_routes_to_update_self():
    # A typed command (spoken=False) walks the same tool-call path as speech; the
    # model's tool pick is what determines routing, not the transcript text.
    update = UpdateSkill()
    fallback = FallbackSkill()
    reg = _registry(update, default=fallback)
    llm = ScriptedLLM(tool_responses=[ChatResponse(tool_calls=[ToolCall("update_self", {})])])

    result, skill = await _orch(llm, reg, tool_mode="native").handle(
        "update yourself", [], spoken=False
    )

    assert skill is update
    assert result.expects_reply is True  # confirmation prompt, not an immediate restart
    assert result.restart is False
    assert fallback.calls == 0


async def test_direct_answer_when_model_calls_no_tool():
    fallback = FallbackSkill()
    reg = _registry(EchoSkill(), default=fallback)
    llm = ScriptedLLM(tool_responses=[ChatResponse(content="Paris is the capital.")])

    result, skill = await _orch(llm, reg, tool_mode="native").handle(
        "capital of France?", [], spoken=True
    )

    assert result.speech == "Paris is the capital."
    assert skill is None  # answered directly, no skill involved
    assert fallback.calls == 0


async def test_delegated_direct_answer_passes_refusal_as_draft():
    # With persona delegation on, a no-tool direct answer (here a refusal) must be
    # handed to the default skill as a draft to re-voice faithfully — NOT re-derived,
    # which is how an honest refusal used to be laundered into a fabricated success.
    fallback = FallbackSkill(speech="Ugh, fine, no.")
    reg = _registry(EchoSkill(), default=fallback)
    llm = ScriptedLLM(tool_responses=[ChatResponse(content="I cannot set recurring reminders.")])

    result, skill = await _orch(
        llm, reg, tool_mode="native", delegate_direct_answers=True
    ).handle("remind me every 15 minutes to stretch", [], spoken=True)

    assert skill is fallback
    assert fallback.calls == 1
    # The refusal rides through as a draft; the skill never sees only the raw request.
    assert fallback.received.slots.get("draft") == "I cannot set recurring reminders."
    assert result.speech == "Ugh, fine, no."


async def test_native_failure_falls_back_to_json_tool_selection():
    echo = EchoSkill(speech="echoed jj")
    reg = _registry(echo, default=FallbackSkill())
    llm = ScriptedLLM(
        chat_tools_raises=True,
        complete_responses=['{"tool": "echo", "arguments": {"text": "jj"}}'],
    )

    result, skill = await _orch(llm, reg, tool_mode="auto").handle(
        "echo jj please", [], spoken=True
    )

    assert result.speech == "echoed jj"
    assert skill is echo
    assert echo.received.slots == {"text": "jj"}
    assert llm.chat_tools_calls == 1  # native attempted
    assert llm.complete_calls == 1  # then JSON fallback


async def test_loop_respects_max_tool_rounds_then_answers():
    data = DataOnlySkill()  # never returns speech -> loop would spin forever unbounded
    fallback = FallbackSkill(speech="answering directly")
    reg = _registry(data, default=fallback)
    llm = ScriptedLLM(
        tool_responses=[ChatResponse(tool_calls=[ToolCall("lookup", {})]) for _ in range(5)]
    )

    result, skill = await _orch(llm, reg, tool_mode="native", max_tool_rounds=2).handle(
        "look something up", [], spoken=True
    )

    assert data.calls == 2  # exactly max_tool_rounds executions, not more
    assert llm.chat_tools_calls == 2
    assert result.speech == "answering directly"  # fell through to the general fallback
    assert skill is fallback


async def test_turn_timeout_degrades_to_general_fallback():
    class SlowLLM(ScriptedLLM):
        async def chat_tools(self, messages, *, system=None, tools=None, label=""):
            self.chat_tools_calls += 1
            await asyncio.sleep(1.0)  # blows the tiny turn budget below
            return ChatResponse(tool_calls=[ToolCall("lookup", {})])

    data = DataOnlySkill()
    fallback = FallbackSkill(speech="fell back")
    reg = _registry(data, default=fallback)
    llm = SlowLLM()

    result, skill = await _orch(
        llm, reg, tool_mode="native", turn_timeout_s=0.01
    ).handle("look something up", [], spoken=True)

    assert result.speech == "fell back"  # timed out -> general fallback
    assert skill is fallback
    assert data.calls == 0  # never got to dispatch a tool


async def test_repeated_same_tool_breaks_to_fallback():
    # A model that keeps re-calling one no-speech tool must break to the fallback
    # after the repeat cap, well before exhausting a generous round budget.
    data = DataOnlySkill()
    fallback = FallbackSkill(speech="answering directly")
    reg = _registry(data, default=fallback)
    llm = ScriptedLLM(
        tool_responses=[ChatResponse(tool_calls=[ToolCall("lookup", {})]) for _ in range(10)]
    )

    result, skill = await _orch(llm, reg, tool_mode="native", max_tool_rounds=10).handle(
        "look something up", [], spoken=True
    )

    assert data.calls == Orchestrator._TOOL_REPEAT_CAP  # ran twice, not ten times
    assert llm.chat_tools_calls == Orchestrator._TOOL_REPEAT_CAP + 1  # +1 that tripped the cap
    assert result.speech == "answering directly"
    assert skill is fallback


async def test_unknown_tool_name_falls_back_to_general():
    fallback = FallbackSkill(speech="general answer")
    reg = _registry(EchoSkill(), default=fallback)
    llm = ScriptedLLM(tool_responses=[ChatResponse(tool_calls=[ToolCall("nonexistent", {})])])

    result, skill = await _orch(llm, reg, tool_mode="native").handle(
        "do a thing", [], spoken=True
    )

    assert result.speech == "general answer"
    assert skill is fallback


async def test_tool_call_logs_route_trace(caplog):
    echo = EchoSkill(speech="echoed hi")
    reg = _registry(echo, default=FallbackSkill())
    llm = ScriptedLLM(tool_responses=[ChatResponse(tool_calls=[ToolCall("echo", {"text": "hi"})])])

    with caplog.at_level(logging.INFO, logger="assistant.core.orchestrator"):
        await _orch(llm, reg, tool_mode="native").handle("please echo hi", [], spoken=True)

    record = next(r for r in caplog.records if getattr(r, "data", None))
    assert record.getMessage() == "Tool call: echo"
    assert record.data == {"kind": "route.tool", "tool": "echo", "arguments": {"text": "hi"}}


async def test_direct_answer_logs(caplog):
    reg = _registry(EchoSkill(), default=FallbackSkill())
    llm = ScriptedLLM(tool_responses=[ChatResponse(content="Paris is the capital.")])

    with caplog.at_level(logging.INFO, logger="assistant.core.orchestrator"):
        await _orch(llm, reg, tool_mode="native").handle("capital of France?", [], spoken=True)

    assert any(r.getMessage() == "Direct answer (no tool)" for r in caplog.records)


def _turn_record(caplog):
    records = [
        r.data for r in caplog.records
        if isinstance(getattr(r, "data", None), dict) and r.data.get("kind") == "turn"
    ]
    assert len(records) == 1  # exactly one turn record per handle() call
    return records[0]


async def test_tool_path_emits_turn_record(caplog):
    echo = EchoSkill(speech="echoed hi")
    reg = _registry(echo, default=FallbackSkill())
    llm = ScriptedLLM(tool_responses=[ChatResponse(tool_calls=[ToolCall("echo", {"text": "hi"})])])
    history = [Turn("user", "earlier"), Turn("assistant", "sure")]

    with caplog.at_level(logging.INFO, logger="assistant.core.orchestrator"):
        await _orch(llm, reg, tool_mode="native").handle("please echo hi", history, spoken=True)

    turn = _turn_record(caplog)
    assert turn["route"] == "tool"
    assert turn["text"] == "please echo hi"
    assert turn["spoken"] is True
    assert turn["history"] == [
        {"role": "user", "content": "earlier"},
        {"role": "assistant", "content": "sure"},
    ]
    assert turn["tool"] == "echo"
    assert turn["slots"] == {"text": "hi"}
    assert turn["skill"] == "echo"
    assert turn["speech"] == "echoed hi"
    assert turn["success"] is True


async def test_direct_answer_emits_turn_record(caplog):
    reg = _registry(EchoSkill(), default=FallbackSkill())
    llm = ScriptedLLM(tool_responses=[ChatResponse(content="Paris is the capital.")])

    with caplog.at_level(logging.INFO, logger="assistant.core.orchestrator"):
        await _orch(llm, reg, tool_mode="native").handle("capital of France?", [], spoken=False)

    turn = _turn_record(caplog)
    assert turn["route"] == "direct"
    assert turn["spoken"] is False
    assert turn["tool"] is None
    assert turn["skill"] is None
    assert turn["speech"] == "Paris is the capital."


async def test_fallback_emits_turn_record(caplog):
    fallback = FallbackSkill(speech="general answer")
    reg = _registry(EchoSkill(), default=fallback)
    llm = ScriptedLLM(chat_tools_raises=True)

    with caplog.at_level(logging.INFO, logger="assistant.core.orchestrator"):
        await _orch(llm, reg, tool_mode="native").handle("do a thing", [], spoken=True)

    turn = _turn_record(caplog)
    assert turn["route"] == "fallback"
    assert turn["tool"] is None
    assert turn["skill"] == "general"
    assert turn["speech"] == "general answer"


async def test_routing_guidance_rides_tool_decision_calls_only():
    # The routing rule is appended to the orchestrator's decide system prompt (both
    # the native and JSON paths) but must never leak into GeneralSkill's answer path.
    from assistant.core.orchestrator import _ROUTING_GUIDANCE
    from assistant.skills.general import GeneralSkill

    class RecordingLLM(ScriptedLLM):
        def __init__(self, **kw):
            super().__init__(**kw)
            self.systems = []
            self.complete_systems = []

        async def chat_tools(self, messages, *, system=None, tools=None, label=""):
            self.systems.append(system)
            return await super().chat_tools(messages, system=system, tools=tools, label=label)

        async def complete(self, prompt, *, system=None, json=False, label=""):  # noqa: A002
            self.complete_systems.append(system)
            return await super().complete(prompt, system=system, json=json, label=label)

    reg = _registry(EchoSkill(), default=FallbackSkill())
    llm = RecordingLLM(
        chat_tools_raises=True,
        complete_responses=['{"answer": "fine"}'],
    )
    await _orch(llm, reg, tool_mode="auto", system_prompt="BASE").handle("hi", [], spoken=True)

    assert llm.systems == [llm.complete_systems[0]]  # same decide system on both paths
    assert llm.systems[0].startswith("BASE")
    assert "web_search" in llm.systems[0]
    assert _ROUTING_GUIDANCE.strip() in llm.systems[0]
    # GeneralSkill keeps the un-augmented prompt.
    assert "web_search" not in GeneralSkill(llm, "BASE")._system


async def test_tool_decision_request_is_persona_free_native_and_json():
    # FTHR-009 (PLM-003 FC-9a) hardening: persona is scoped to spoken replies
    # only (core/persona.py); it must never ride the tool-decision request
    # (system + messages + tool schemas), in EITHER tool_mode path. Asserted
    # against the persona block *content* imported from persona.py, not a
    # copied string, so a future persona v3 keeps this test honest.
    persona_terse = persona.persona_segment("terse")
    persona_expansive = persona.persona_segment("expansive")

    class RecordingLLM(ScriptedLLM):
        def __init__(self, **kw):
            super().__init__(**kw)
            self.tool_calls_seen = []
            self.complete_calls_seen = []

        async def chat_tools(self, messages, *, system=None, tools=None, label=""):
            self.tool_calls_seen.append((system, messages, tools))
            return await super().chat_tools(messages, system=system, tools=tools, label=label)

        async def complete(self, prompt, *, system=None, json=False, label=""):  # noqa: A002
            self.complete_calls_seen.append((system, prompt))
            return await super().complete(prompt, system=system, json=json, label=label)

    reg = _registry(EchoSkill(), default=FallbackSkill())

    # Native tool-calling path.
    native_llm = RecordingLLM(tool_responses=[ChatResponse(content="fine")])
    await _orch(native_llm, reg, tool_mode="native", persona_suffix=persona_terse).handle(
        "hi", [], spoken=True
    )
    system, messages, tools = native_llm.tool_calls_seen[0]
    # str(), not json.dumps(): persona text carries raw quotes that json.dumps
    # would backslash-escape, which would mask the substring on a real leak.
    blob = str(system) + str(messages) + str(tools)
    assert persona_terse not in blob
    assert persona_expansive not in blob

    # JSON-coerced path (native forced to fail, same pattern as
    # test_native_failure_falls_back_to_json_tool_selection).
    json_llm = RecordingLLM(chat_tools_raises=True, complete_responses=['{"answer": "fine"}'])
    await _orch(json_llm, reg, tool_mode="auto", persona_suffix=persona_terse).handle(
        "hi", [], spoken=True
    )
    system, prompt = json_llm.complete_calls_seen[0]
    blob = str(system) + str(prompt)
    assert persona_terse not in blob
    assert persona_expansive not in blob
