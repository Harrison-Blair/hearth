from assistant.llm.base import ChatResponse
from assistant.llm.fallback_provider import FallbackLLMProvider


class FakeLLM:
    """Scriptable LLMProvider stub. Raises if ``raises`` is set, else returns
    ``text`` / ``chat_response``."""

    def __init__(
        self,
        *,
        text: str = "primary",
        chat_response: ChatResponse | None = None,
        raises: Exception | None = None,
        health: bool = True,
    ) -> None:
        self._text = text
        self._chat_response = chat_response or ChatResponse(content=text)
        self._raises = raises
        self._health = health
        self.calls = 0

    async def complete(self, prompt, *, system=None, json=False, label=""):
        self.calls += 1
        if self._raises:
            raise self._raises
        return self._text

    async def chat(self, messages, *, system=None, label=""):
        self.calls += 1
        if self._raises:
            raise self._raises
        return self._text

    async def chat_tools(self, messages, *, system=None, tools=None, label=""):
        self.calls += 1
        if self._raises:
            raise self._raises
        return self._chat_response

    async def health(self):
        return self._health

    async def aclose(self):
        pass


async def test_complete_uses_primary_when_healthy():
    primary = FakeLLM(text="from-primary")
    fb = FallbackLLMProvider(primary, FakeLLM(text="from-fallback"))
    assert await fb.complete("hi") == "from-primary"
    assert primary.calls == 1


async def test_complete_falls_back_on_primary_failure():
    primary = FakeLLM(raises=RuntimeError("zen down"))
    fallback = FakeLLM(text="from-fallback")
    fb = FallbackLLMProvider(primary, fallback)
    assert await fb.complete("hi") == "from-fallback"
    assert primary.calls == 1


async def test_chat_falls_back_on_primary_failure():
    primary = FakeLLM(raises=RuntimeError("timeout"))
    fallback = FakeLLM(text="from-fallback")
    fb = FallbackLLMProvider(primary, fallback)
    assert await fb.chat([{"role": "user", "content": "hi"}]) == "from-fallback"


async def test_chat_tools_falls_back_on_primary_failure():
    primary = FakeLLM(raises=RuntimeError("timeout"))
    fallback = FakeLLM(chat_response=ChatResponse(content="fallback-answer"))
    fb = FallbackLLMProvider(primary, fallback)
    resp = await fb.chat_tools([{"role": "user", "content": "hi"}])
    assert resp.content == "fallback-answer"


async def test_chat_tools_returns_primary_response_when_no_call():
    primary = FakeLLM(chat_response=ChatResponse(content="", tool_calls=[]))
    fallback = FakeLLM(chat_response=ChatResponse(content="fallback"))
    fb = FallbackLLMProvider(primary, fallback)
    resp = await fb.chat_tools([{"role": "user", "content": "hi"}])
    # Empty primary response does NOT fall back — orchestrator handles empties.
    assert resp.content == ""
    assert primary.calls == 1


async def test_health_true_when_either_healthy():
    fb = FallbackLLMProvider(FakeLLM(health=False), FakeLLM(health=True))
    assert await fb.health() is True


async def test_health_true_when_both_healthy():
    fb = FallbackLLMProvider(FakeLLM(health=True), FakeLLM(health=True))
    assert await fb.health() is True


async def test_health_false_when_both_down():
    fb = FallbackLLMProvider(FakeLLM(health=False), FakeLLM(health=False))
    assert await fb.health() is False


async def test_label_passed_through_to_primary():
    seen = {}

    class LabelSpy:
        async def complete(self, prompt, *, system=None, json=False, label=""):
            seen["label"] = label
            return "ok"

        async def chat(self, messages, *, system=None, label=""):
            return "ok"

        async def chat_tools(self, messages, *, system=None, tools=None, label=""):
            return ChatResponse(content="ok")

        async def health(self):
            return True

        async def aclose(self):
            pass

    fb = FallbackLLMProvider(LabelSpy(), FakeLLM())
    await fb.complete("hi", label="agent")
    assert seen["label"] == "agent"
