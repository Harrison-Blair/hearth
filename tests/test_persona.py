"""Persona layer: composition helpers, terminal-only injection, and isolation
of the tool-decision / JSON-structured paths."""

from assistant.core import persona
from assistant.core.config import Config, PersonaConfig
from assistant.core.events import Command, Intent, SkillResult, ToolCall
from assistant.core.orchestrator import Orchestrator
from assistant.llm.base import ChatResponse
from assistant.search.base import SearchResult
from assistant.skills.base import Skill, SkillRegistry
from assistant.skills.general import GeneralSkill
from assistant.skills.weather import WeatherSkill
from assistant.skills.web_search import WebSearchSkill
from assistant.weather.base import Forecast


# --- persona module -------------------------------------------------------


def test_disabled_suffix_is_empty_and_composition_is_byte_identical():
    assert persona.suffix(enabled=False, strength="terse") == ""
    assert persona.suffix(enabled=False, strength="expansive") == ""
    # No suffix -> the base prompt is returned untouched.
    assert persona.with_persona("base prompt", "") == "base prompt"


def test_enabled_suffix_carries_the_voice_and_variants_differ():
    terse = persona.suffix(enabled=True, strength="terse")
    expansive = persona.suffix(enabled=True, strength="expansive")
    assert "Calcifer" in terse and "Calcifer" in expansive
    assert terse != expansive


def test_unknown_strength_falls_back_to_terse():
    assert persona.persona_segment("bogus") == persona.persona_segment("terse")


def test_with_persona_appends_after_the_base():
    seg = persona.persona_segment("terse")
    composed = persona.with_persona("BASE", seg)
    assert composed.startswith("BASE")
    assert composed.endswith(seg)
    assert seg in composed


# --- GeneralSkill: persona rides the final reply --------------------------


class _RecordingChatLLM:
    def __init__(self, answer="Paris."):
        self.answer = answer
        self.systems = []

    async def chat(self, messages, *, system=None, label=""):
        self.systems.append(system)
        return self.answer

    async def health(self):
        return True


async def test_general_skill_appends_persona_to_reply_prompt():
    llm = _RecordingChatLLM()
    suffix = persona.suffix(enabled=True, strength="terse")
    await GeneralSkill(llm, "be brief", persona_suffix=suffix).handle(
        Command("capital of France"), Intent("general")
    )
    assert "be brief" in llm.systems[0]
    assert "Calcifer" in llm.systems[0]


async def test_general_skill_default_is_persona_free():
    llm = _RecordingChatLLM()
    await GeneralSkill(llm, "be brief").handle(Command("?"), Intent("general"))
    assert llm.systems == ["be brief"]


# --- Weather: persona on the terminal complete only -----------------------


class _RecordingCompleteLLM:
    def __init__(self, answer="Sunny, 72 degrees.", json_responses=None):
        self.answer = answer
        self.json_responses = list(json_responses or [])
        self.systems = []

    async def complete(self, prompt, *, system=None, json=False, label=""):  # noqa: A002
        self.systems.append(system)
        if json:
            return self.json_responses.pop(0) if self.json_responses else "not json"
        return self.answer

    async def health(self):
        return True


class _FakeWeather:
    async def forecast(self, lat, lon, *, name):
        return Forecast(
            location=name,
            current={"temp": 72, "apparent": 70, "description": "clear", "wind": 5, "humidity": 50},
            daily=[{"date": "2026-07-06", "weekday": "Monday", "description": "clear",
                    "high": 90, "low": 70, "precip_prob": 5, "precip": 0.0, "wind_max": 8}],
            units={"temp": "°F", "wind": "mph", "precip": "inch"},
        )

    async def geocode(self, place):
        return None

    async def health(self):
        return True


async def test_weather_answer_carries_persona():
    llm = _RecordingCompleteLLM()
    suffix = persona.suffix(enabled=True, strength="terse")
    skill = WeatherSkill(
        _FakeWeather(), llm, home_lat=0.0, home_lon=0.0, home_name="Home",
        persona_suffix=suffix,
    )
    await skill.handle(Command("weather today"), Intent("weather"))
    assert "Calcifer" in llm.systems[0]
    assert "forecast" in llm.systems[0]  # base weather instructions still present


# --- Web search: persona on the plain-summary fallback, NOT the JSON assess


class _FakeSearch:
    def __init__(self, results):
        self._results = results

    async def search(self, query, *, count):
        return self._results

    async def health(self):
        return True


async def test_web_search_persona_only_on_plain_summary_not_json_assess():
    # refine returns a query; the assess call then gets no queued JSON ("not json"),
    # so the skill falls back to the plain-text summary.
    llm = _RecordingCompleteLLM(
        answer="Rain, according to bbc.com.",
        json_responses=['{"query": "weather"}'],
    )
    suffix = persona.suffix(enabled=True, strength="terse")
    result = SearchResult(title="t", snippet="facts", source="bbc.com", url="https://bbc.com/x")
    skill = WebSearchSkill(
        _FakeSearch([result]), llm, count=1, max_rounds=1, persona_suffix=suffix
    )
    await skill.handle(Command("search the web for weather"), Intent("web_search"))

    # systems: [refine=None, assess=_ASSESS_SYSTEM, summary=persona-composed]
    assess_system = llm.systems[1]
    summary_system = llm.systems[-1]
    assert assess_system is not None and "Calcifer" not in assess_system  # JSON path stays clean
    assert "Calcifer" in summary_system  # plain-text terminal reply carries the voice


# --- Orchestrator: direct-answer delegation + tool-decision isolation ------


class _RecordingScriptedLLM:
    def __init__(self, tool_responses):
        self._tool_responses = list(tool_responses)
        self.tool_systems = []
        self.chat_tools_calls = 0

    async def chat_tools(self, messages, *, system=None, tools=None, label=""):
        self.chat_tools_calls += 1
        self.tool_systems.append(system)
        return self._tool_responses.pop(0)

    async def complete(self, prompt, *, system=None, json=False, label=""):  # noqa: A002
        raise AssertionError("native mode should not reach complete()")

    async def chat(self, messages, *, system=None, label=""):
        raise AssertionError("orchestrator should not call chat()")

    async def health(self):
        return True


class _CountingGeneral(Skill):
    name = "general"
    intents = {"general"}

    def __init__(self):
        self.calls = 0

    def tools(self):
        return []

    async def handle(self, cmd, intent):
        self.calls += 1
        return SkillResult(speech="Fine, fine — Paris.")


class _EchoSkill(Skill):
    name = "echo"
    intents = {"echo"}
    tool_specs = {
        "echo": {
            "description": "echo text",
            "parameters": {"type": "object", "properties": {"text": {"type": "string"}}},
        }
    }

    def __init__(self):
        self.received = None

    async def handle(self, cmd, intent):
        self.received = intent
        return SkillResult(speech="echoed")


def _registry(*skills, default):
    reg = SkillRegistry()
    for s in skills:
        reg.register(s)
    reg.register(default, default=True)
    return reg


async def test_direct_answer_delegates_to_general_when_enabled():
    general = _CountingGeneral()
    reg = _registry(_EchoSkill(), default=general)
    llm = _RecordingScriptedLLM([ChatResponse(content="Paris.")])
    orch = Orchestrator(
        llm, reg, tool_mode="native", system_prompt="BASE", delegate_direct_answers=True
    )

    result, _ = await orch.handle("capital of France?", [], spoken=True)

    assert general.calls == 1  # regenerated through the persona-bearing skill
    assert result.speech == "Fine, fine — Paris."
    # The tool-decision call was made with the persona-free base prompt.
    assert llm.tool_systems == ["BASE"]


async def test_direct_answer_verbatim_when_disabled():
    general = _CountingGeneral()
    reg = _registry(_EchoSkill(), default=general)
    llm = _RecordingScriptedLLM([ChatResponse(content="Paris.")])
    orch = Orchestrator(llm, reg, tool_mode="native", system_prompt="BASE")

    result, skill = await orch.handle("capital of France?", [], spoken=True)

    assert result.speech == "Paris."  # spoken verbatim, no extra call
    assert skill is None
    assert general.calls == 0


async def test_tool_call_arguments_unaffected_by_delegation():
    echo = _EchoSkill()
    reg = _registry(echo, default=_CountingGeneral())
    llm = _RecordingScriptedLLM([ChatResponse(tool_calls=[ToolCall("echo", {"text": "hi"})])])
    orch = Orchestrator(
        llm, reg, tool_mode="native", system_prompt="BASE", delegate_direct_answers=True
    )

    await orch.handle("echo hi", [], spoken=True)

    assert echo.received.slots == {"text": "hi"}  # structured args intact
    assert llm.tool_systems == ["BASE"]  # persona never entered tool selection


# --- Config ---------------------------------------------------------------


def test_persona_config_defaults():
    assert PersonaConfig().enabled is True  # persona is on by default
    assert PersonaConfig().strength == "terse"
    cfg = Config()  # mirrored in config.yaml
    assert cfg.persona.enabled is True
    assert cfg.persona.strength == "terse"


def test_persona_env_overrides(monkeypatch):
    monkeypatch.setenv("ASSISTANT_PERSONA__ENABLED", "false")
    monkeypatch.setenv("ASSISTANT_PERSONA__STRENGTH", "expansive")
    cfg = Config()
    assert cfg.persona.enabled is False  # override switches the default off
    assert cfg.persona.strength == "expansive"
