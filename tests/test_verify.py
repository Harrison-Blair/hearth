"""Tests for the verify module: Verdict parsing, stage-specific extraction,
fail-open on malformed input, and the persona-on-spoken-outputs-only contract."""

import json

from assistant.core.verify import (
    Verdict,
    _build_prompt,
    verify,
)


class FakeLLM:
    """Returns a fixed raw string for ``complete``; records the prompt/system."""

    def __init__(self, raw: str):
        self._raw = raw
        self.prompt = ""
        self.system = ""
        self.label = ""
        self.calls = 0

    async def complete(self, prompt, *, system=None, json=False, label=""):  # noqa: A002
        self.calls += 1
        self.prompt = prompt
        self.system = system
        self.label = label
        return self._raw

    async def chat(self, messages, *, system=None, label=""):
        raise AssertionError("verify should not call chat()")

    async def chat_tools(self, messages, *, system=None, tools=None, label=""):
        raise AssertionError("verify should not call chat_tools()")

    async def health(self):
        return True


def _ctx(stage):
    base = {
        "request": "what's the weather",
        "history": [{"role": "user", "content": "hi"}],
        "tool": "weather",
        "arguments": {"when": "today"},
    }
    if stage == "post":
        base["result"] = {"temp": 72}
        base["draft_speech"] = "It's 72 degrees today."
    return base


async def test_pre_approve():
    llm = FakeLLM(json.dumps({"decision": "approve"}))
    v = await verify("pre", _ctx("pre"), llm=llm)
    assert isinstance(v, Verdict)
    assert v.decision == "approve"
    assert v.feedback == ""
    assert v.rewritten_tool == ""
    assert v.rewritten_arguments == {}
    assert v.rewritten_speech == ""
    assert llm.label == "verify"


async def test_post_approve():
    llm = FakeLLM(json.dumps({"decision": "approve"}))
    v = await verify("post", _ctx("post"), llm=llm)
    assert v.decision == "approve"
    assert v.rewritten_speech == ""


async def test_pre_rewrite_extracts_tool_and_args():
    llm = FakeLLM(
        json.dumps(
            {
                "decision": "rewrite",
                "rewritten_tool": "web_search",
                "rewritten_arguments": {"query": "weather today"},
            }
        )
    )
    v = await verify("pre", _ctx("pre"), llm=llm)
    assert v.decision == "rewrite"
    assert v.rewritten_tool == "web_search"
    assert v.rewritten_arguments == {"query": "weather today"}
    assert v.rewritten_speech == ""  # post-only field


async def test_post_rewrite_extracts_speech():
    llm = FakeLLM(
        json.dumps(
            {"decision": "rewrite", "rewritten_speech": "It is 72 and sunny."}
        )
    )
    v = await verify("post", _ctx("post"), llm=llm)
    assert v.decision == "rewrite"
    assert v.rewritten_speech == "It is 72 and sunny."
    assert v.rewritten_tool == ""  # pre-only field


async def test_pre_reject_extracts_feedback():
    llm = FakeLLM(
        json.dumps({"decision": "reject", "feedback": "Hmm, let me double check that."})
    )
    v = await verify("pre", _ctx("pre"), llm=llm, persona_suffix="be snarky")
    assert v.decision == "reject"
    assert v.feedback == "Hmm, let me double check that."


async def test_post_reject_extracts_feedback():
    llm = FakeLLM(json.dumps({"decision": "reject", "feedback": "That's not right."}))
    v = await verify("post", _ctx("post"), llm=llm)
    assert v.decision == "reject"
    assert v.feedback == "That's not right."


async def test_non_json_returns_none():
    llm = FakeLLM("not json at all")
    assert await verify("pre", _ctx("pre"), llm=llm) is None


async def test_non_dict_returns_none():
    llm = FakeLLM(json.dumps(["approve"]))
    assert await verify("pre", _ctx("pre"), llm=llm) is None


async def test_missing_decision_returns_none():
    llm = FakeLLM(json.dumps({"rewritten_tool": "weather"}))
    assert await verify("pre", _ctx("pre"), llm=llm) is None


async def test_bad_decision_value_returns_none():
    llm = FakeLLM(json.dumps({"decision": "maybe"}))
    assert await verify("pre", _ctx("pre"), llm=llm) is None


async def test_complete_exception_returns_none():
    class BoomLLM:
        async def complete(self, prompt, *, system=None, json=False, label=""):  # noqa: A002
            raise RuntimeError("llm down")

        async def chat(self, *a, **k):
            ...

        async def chat_tools(self, *a, **k):
            ...

        async def health(self):
            return True

    assert await verify("pre", _ctx("pre"), llm=BoomLLM()) is None


async def test_non_string_feedback_coerced_to_empty():
    llm = FakeLLM(json.dumps({"decision": "reject", "feedback": 42}))
    v = await verify("pre", _ctx("pre"), llm=llm)
    assert v.decision == "reject"
    assert v.feedback == ""


async def test_non_dict_rewritten_arguments_coerced():
    llm = FakeLLM(
        json.dumps(
            {"decision": "rewrite", "rewritten_tool": "weather", "rewritten_arguments": "oops"}
        )
    )
    v = await verify("pre", _ctx("pre"), llm=llm)
    assert v.rewritten_arguments == {}


async def test_spoken_feedback_off_zeroes_feedback():
    llm = FakeLLM(
        json.dumps({"decision": "reject", "feedback": "let me recheck that"})
    )
    v = await verify("pre", _ctx("pre"), llm=llm, spoken_feedback=False)
    assert v.decision == "reject"
    assert v.feedback == ""  # we didn't ask for it; never honor it


# ---- prompt-construction: persona on spoken outputs only ---------------------


def test_prompt_pre_includes_feedback_field_when_spoken():
    p = _build_prompt("pre", _ctx("pre"), persona_suffix="", spoken_feedback=True)
    assert '"feedback"' in p
    assert '"rewritten_tool"' in p
    assert '"rewritten_arguments"' in p


def test_prompt_pre_omits_feedback_field_when_silent():
    p = _build_prompt("pre", _ctx("pre"), persona_suffix="", spoken_feedback=False)
    assert '"feedback"' not in p
    assert '"rewritten_tool"' in p  # routing rewrite stays


def test_prompt_post_includes_rewritten_speech_field():
    p = _build_prompt("post", _ctx("post"), persona_suffix="", spoken_feedback=True)
    assert '"rewritten_speech"' in p
    assert '"feedback"' in p


def test_prompt_persona_appears_and_is_scoped_to_spoken_fields():
    persona = "You are Calcifer: sardonic fire-demon."
    # pre + spoken: persona rides feedback only.
    p = _build_prompt("pre", _ctx("pre"), persona_suffix=persona, spoken_feedback=True)
    assert persona in p
    assert "NEVER to `decision`" in p
    assert "`feedback`" in p
    assert "`rewritten_speech`" not in p  # pre stage has no rewritten_speech


def test_prompt_persona_omitted_for_pre_when_silent():
    # pre + silent: no spoken field at all → persona must not appear (no leak
    # onto the routing rewrite).
    p = _build_prompt("pre", _ctx("pre"), persona_suffix=" Calcifer ", spoken_feedback=False)
    assert "Calcifer" not in p


def test_prompt_persona_for_post_silent_rides_rewritten_speech_only():
    persona = "Calcifer voice."
    p = _build_prompt("post", _ctx("post"), persona_suffix=persona, spoken_feedback=False)
    assert persona in p
    assert "`rewritten_speech`" in p
    assert "`feedback`" not in p  # feedback is gated by spoken_feedback
    assert "NEVER to `decision`" in p


def test_prompt_decision_rules_are_persona_free():
    # The verdict rules and the stage rewrite instructions never carry persona.
    persona = "UNIQUE_PERSONA_MARKER"
    p = _build_prompt("post", _ctx("post"), persona_suffix=persona, spoken_feedback=True)
    # Persona only appears once, in the trailing voice note — not in the rules.
    assert p.count(persona) == 1
    rules = p.split("Verdicts (decide on correctness alone):")[1].split("Reply with")[0]
    assert persona not in rules


def test_prompt_post_stage_shows_result_and_draft():
    p = _build_prompt("post", _ctx("post"), persona_suffix="", spoken_feedback=True)
    assert "It's 72 degrees today." in p
    assert '"temp": 72' in p


def test_prompt_pre_stage_shows_pick_not_result():
    p = _build_prompt("pre", _ctx("pre"), persona_suffix="", spoken_feedback=True)
    assert "Picked tool: weather" in p
    assert '"when": "today"' in p
    assert "Drafted answer" not in p  # pre stage has no draft yet
