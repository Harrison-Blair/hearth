from assistant.core.events import Command, Intent
from assistant.skills.general import GeneralSkill


class FakeLLM:
    def __init__(self, answer="", exc=None):
        self.answer = answer
        self.exc = exc
        self.calls = []

    async def complete(self, prompt, *, system=None, json=False):
        self.calls.append((prompt, system))
        if self.exc:
            raise self.exc
        return self.answer

    async def health(self):
        return True


async def test_returns_llm_answer():
    llm = FakeLLM("Paris.")
    result = await GeneralSkill(llm, "be brief").handle(
        Command("capital of France"), Intent("general")
    )
    assert result.speech == "Paris."
    assert result.success
    assert llm.calls == [("capital of France", "be brief")]


async def test_empty_answer_is_unsuccessful():
    result = await GeneralSkill(FakeLLM(""), "x").handle(Command("?"), Intent("general"))
    assert not result.success


async def test_llm_error_is_handled():
    skill = GeneralSkill(FakeLLM(exc=RuntimeError("boom")), "x")
    result = await skill.handle(Command("?"), Intent("general"))
    assert not result.success
    assert "couldn't reach" in result.speech.lower()
