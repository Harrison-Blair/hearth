"""Live tool-call evaluation harness.

Measures whether the *configured* Ollama model produces correctly-formatted tool
calls through the real orchestrator decision path: for each dataset case we run
the orchestrator's tool decision (native tool-calling -> JSON fallback, exactly as
production does) and score tool-name correctness + required-argument presence,
plus the direct-answer cases. The aggregate is the reference doc's Stage-1 gate.

The orchestrator is built as ``assistant.app`` builds it (same LLM, skill
registry, tool schemas, and system prompt), minus audio/TTS.

Run standalone:  ``ASSISTANT_EVAL=1 python -m tests.eval.run_eval``
Or via pytest:   ``tests/eval/test_tool_eval.py`` (opt-in + skips when offline).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from assistant.core.config import Config
from assistant.core.orchestrator import Orchestrator
from assistant.llm.base import LLMProvider
from assistant.llm.ollama_provider import OllamaProvider
from assistant.search.wikipedia import WikipediaSearch
from assistant.skills.base import SkillRegistry
from assistant.skills.clock import ClockSkill
from assistant.skills.general import GeneralSkill
from assistant.skills.reminder import ReminderSkill
from assistant.skills.timer import TimerSkill
from assistant.skills.weather import WeatherSkill
from assistant.skills.web_search import WebSearchSkill
from assistant.storage.reminders import ReminderStore
from assistant.weather.open_meteo import OpenMeteoWeather

from tests.eval.dataset import CASES, Case

PASS_THRESHOLD = 0.90


def _build_llm(config: Config) -> OllamaProvider:
    return OllamaProvider(
        config.llm.model, config.llm.host, config.llm.timeout, config.llm.health_timeout
    )


def build_orchestrator(config: Config, llm: LLMProvider) -> Orchestrator:
    """Construct the real skill registry + orchestrator exactly as ``assistant.app``
    does, minus audio/TTS. Skills are wired with their real dependencies so the tool
    schemas match production; they are never executed here (we only score the tool
    decision), so an in-memory store and no progress speaker are enough."""
    store = ReminderStore(":memory:")
    weather = OpenMeteoWeather(
        forecast_endpoint=config.weather.forecast_endpoint,
        geocoding_endpoint=config.weather.geocoding_endpoint,
        temperature_unit=config.weather.temperature_unit,
        wind_speed_unit=config.weather.wind_speed_unit,
        precipitation_unit=config.weather.precipitation_unit,
        timezone=config.weather.timezone,
        forecast_days=config.weather.forecast_days,
        timeout=config.weather.timeout,
    )
    search = WikipediaSearch(
        language=config.web_search.language,
        result_count=config.web_search.result_count,
        timeout=config.web_search.timeout,
        max_snippet_chars=config.web_search.max_snippet_chars,
    )
    registry = SkillRegistry()
    registry.register(ClockSkill())
    registry.register(ReminderSkill(store, llm))
    registry.register(TimerSkill(store))
    registry.register(WebSearchSkill(
        search, llm,
        count=config.web_search.result_count,
        max_rounds=config.web_search.max_rounds,
        speaker=None,
        progress_updates=False,
    ))
    registry.register(WeatherSkill(
        weather, llm,
        home_lat=config.weather.latitude,
        home_lon=config.weather.longitude,
        home_name=config.weather.location_name,
    ))
    registry.register(GeneralSkill(llm, config.llm.system_prompt), default=True)
    return Orchestrator(
        llm,
        registry,
        tool_mode=config.agent.tool_mode,
        max_tool_rounds=config.agent.max_tool_rounds,
        system_prompt=config.llm.system_prompt,
    )


@dataclass
class CaseResult:
    case: Case
    passed: bool
    got: str  # human-readable summary of what the model produced


def _has_arg(args: dict, key: str) -> bool:
    val = args.get(key)
    return val is not None and str(val).strip() != ""


async def evaluate(orch: Orchestrator, case: Case) -> CaseResult:
    resp = await orch._decide(Orchestrator._messages(case.utterance, []))
    call = resp.tool_calls[0] if resp.tool_calls else None

    if case.tool is None:  # expect a direct answer, no tool
        passed = call is None and bool(resp.content)
        return CaseResult(case, passed, "direct answer" if call is None else f"tool {call.name}")

    if call is None:
        return CaseResult(case, False, "direct answer" if resp.content else "no decision")
    if call.name != case.tool:
        return CaseResult(case, False, f"tool {call.name}")

    missing = [a for a in case.required_args if not _has_arg(call.arguments, a)]
    implausible = [
        a for a, sub in case.arg_contains.items()
        if sub.lower() not in str(call.arguments.get(a, "")).lower()
    ]
    passed = not missing and not implausible
    return CaseResult(case, passed, f"tool {call.name} args={call.arguments}")


async def run_eval(config: Config) -> tuple[float, list[CaseResult]]:
    """Run every case through a freshly-built orchestrator. Assumes Ollama is
    reachable (the caller gates on ``check_reachable``)."""
    llm = _build_llm(config)
    try:
        orch = build_orchestrator(config, llm)
        results = [await evaluate(orch, case) for case in CASES]
    finally:
        await llm.aclose()
    score = sum(r.passed for r in results) / len(results)
    return score, results


async def check_reachable(config: Config) -> bool:
    llm = _build_llm(config)
    try:
        return await llm.health()
    finally:
        await llm.aclose()


def format_table(results: list[CaseResult], score: float) -> str:
    lines = [f"{'':4}{'utterance':<48}{'expected':<18}got"]
    for r in results:
        expected = r.case.tool or "direct answer"
        mark = "PASS" if r.passed else "FAIL"
        lines.append(f"{mark:<4}{r.case.utterance[:47]:<48}{expected:<18}{r.got}")
    passed = sum(r.passed for r in results)
    lines.append("")
    lines.append(f"score: {passed}/{len(results)} = {score:.0%} (gate {PASS_THRESHOLD:.0%})")
    return "\n".join(lines)


async def _amain(config: Config) -> int:
    if not await check_reachable(config):
        print(
            f"Ollama not reachable at {config.llm.host} or model "
            f"{config.llm.model!r} not pulled; cannot run eval."
        )
        return 1
    score, results = await run_eval(config)
    print(format_table(results, score))
    return 0 if score >= PASS_THRESHOLD else 1


def main() -> int:
    return asyncio.run(_amain(Config()))


if __name__ == "__main__":
    raise SystemExit(main())
