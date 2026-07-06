import asyncio

from assistant.core.events import SkillResult, ToolCall
from assistant.core.orchestrator import Orchestrator
from assistant.llm.base import ChatResponse
from assistant.nlu.keyphrase_router import KeyphraseRouter
from assistant.skills.base import Skill, SkillRegistry


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
        self._speech = speech

    def tools(self):
        return []

    async def handle(self, cmd, intent):
        self.calls += 1
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


def _orch(llm, registry, *, fast_path=None, **kw):
    fp = fast_path if fast_path is not None else KeyphraseRouter(default_intent="general")
    return Orchestrator(llm, registry, fp, **kw)


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


async def test_fast_path_hit_dispatches_without_any_llm_call():
    echo = EchoSkill(speech="echoed")
    reg = _registry(echo, default=FallbackSkill())
    kp = KeyphraseRouter(default_intent="general")
    kp.add("echo", "please echo")
    llm = ScriptedLLM()  # any LLM call would pop from an empty queue and error

    result, skill = await _orch(llm, reg, fast_path=kp).handle(
        "please echo this", [], spoken=True
    )

    assert result.speech == "echoed"
    assert skill is echo
    assert llm.chat_tools_calls == 0
    assert llm.complete_calls == 0


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
