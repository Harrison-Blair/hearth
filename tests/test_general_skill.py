from assistant.core.events import Command, Intent, Turn
from assistant.skills.general import GeneralSkill


class FakeLLM:
    def __init__(self, answer="", exc=None):
        self.answer = answer
        self.exc = exc
        self.calls = []

    async def chat(self, messages, *, system=None, label=""):
        self.calls.append((messages, system))
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
    # Empty history -> a single user message.
    assert llm.calls == [([{"role": "user", "content": "capital of France"}], "be brief")]


async def test_history_precedes_current_text():
    llm = FakeLLM("1965.")
    history = [Turn("user", "who wrote Dune"), Turn("assistant", "Frank Herbert.")]
    await GeneralSkill(llm, "be brief").handle(
        Command("when did he die", history=history), Intent("general")
    )
    messages, _ = llm.calls[0]
    assert messages == [
        {"role": "user", "content": "who wrote Dune"},
        {"role": "assistant", "content": "Frank Herbert."},
        {"role": "user", "content": "when did he die"},
    ]


async def test_empty_answer_is_unsuccessful():
    result = await GeneralSkill(FakeLLM(""), "x").handle(Command("?"), Intent("general"))
    assert not result.success


async def test_llm_error_is_handled():
    skill = GeneralSkill(FakeLLM(exc=RuntimeError("boom")), "x")
    result = await skill.handle(Command("?"), Intent("general"))
    assert not result.success
    assert "couldn't reach" in result.speech.lower()
