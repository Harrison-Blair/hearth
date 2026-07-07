from assistant.core.events import Command, Intent, Turn
from assistant.skills.general import GeneralSkill


class FakeLLM:
    def __init__(self, answer="", exc=None, styled=None, complete_exc=None):
        self.answer = answer
        self.exc = exc
        self.styled = styled
        self.complete_exc = complete_exc
        self.calls = []
        self.complete_calls = []

    async def chat(self, messages, *, system=None, label=""):
        self.calls.append((messages, system))
        if self.exc:
            raise self.exc
        return self.answer

    async def complete(self, prompt, *, system=None, json=False, label=""):  # noqa: A002
        self.complete_calls.append((prompt, system, label))
        if self.complete_exc:
            raise self.complete_exc
        return self.styled

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


async def test_draft_is_restyled_not_reanswered():
    # A draft (the model's own direct answer) must be re-voiced, never re-derived:
    # the re-answer path (chat) would let a refusal turn into a fabricated success.
    llm = FakeLLM(answer="SHOULD NOT BE USED", styled="Ugh, no — I can't do recurring reminders.")
    intent = Intent("general", slots={"draft": "I cannot set recurring reminders."})
    result = await GeneralSkill(llm, "be brief").handle(Command("remind me every 15 min"), intent)
    assert result.speech == "Ugh, no — I can't do recurring reminders."
    assert llm.complete_calls  # restyled via complete()
    assert llm.calls == []  # never re-answered via chat()
    # The draft (ground truth) is carried into the restyle prompt.
    assert "I cannot set recurring reminders." in llm.complete_calls[0][0]


async def test_restyle_falls_back_to_draft_on_error():
    llm = FakeLLM(complete_exc=RuntimeError("boom"))
    intent = Intent("general", slots={"draft": "I can't reach your calendar right now."})
    result = await GeneralSkill(llm, "x").handle(Command("what's on my calendar"), intent)
    assert result.speech == "I can't reach your calendar right now."  # verbatim, never lost


async def test_restyle_empty_falls_back_to_draft():
    llm = FakeLLM(styled="   ")
    intent = Intent("general", slots={"draft": "I cannot set recurring reminders."})
    result = await GeneralSkill(llm, "x").handle(Command("remind me every 15 min"), intent)
    assert result.speech == "I cannot set recurring reminders."
