from assistant.core.events import Intent
from assistant.nlu.classifier_router import ClassifierRouter

INTENTS = {
    "time": "the current clock time",
    "general": "anything else",
}


class FakeLLM:
    def __init__(self, answer="", exc=None):
        self.answer = answer
        self.exc = exc
        self.calls = []

    async def complete(self, prompt, *, system=None, json=False, label=""):
        self.calls.append((prompt, json))
        if self.exc:
            raise self.exc
        return self.answer

    async def health(self):
        return True


class FakeRouter:
    def __init__(self):
        self.calls = []

    async def route(self, text):
        self.calls.append(text)
        return Intent(type="fallback", raw_text=text)


def _router(answer="", exc=None):
    fallback = FakeRouter()
    return ClassifierRouter(FakeLLM(answer=answer, exc=exc), fallback, INTENTS), fallback


async def test_valid_label_routes_without_fallback():
    router, fallback = _router(answer='{"intent": "time"}')
    intent = await router.route("what time is it")
    assert intent.type == "time"
    assert fallback.calls == []


async def test_label_is_normalized():
    router, fallback = _router(answer='{"intent": "  TIME "}')
    intent = await router.route("what time is it")
    assert intent.type == "time"
    assert fallback.calls == []


async def test_unknown_label_falls_back():
    router, fallback = _router(answer='{"intent": "weather"}')
    intent = await router.route("will it rain")
    assert intent.type == "fallback"
    assert fallback.calls == ["will it rain"]


async def test_llm_error_falls_back():
    router, fallback = _router(exc=RuntimeError("boom"))
    intent = await router.route("hello there")
    assert intent.type == "fallback"
    assert fallback.calls == ["hello there"]


async def test_non_json_falls_back():
    router, fallback = _router(answer="sure, that's a time question")
    intent = await router.route("what time is it")
    assert intent.type == "fallback"
    assert fallback.calls == ["what time is it"]


async def test_routed_intent_carries_raw_text():
    router, _ = _router(answer='{"intent": "general"}')
    intent = await router.route("tell me a joke")
    assert intent.raw_text == "tell me a joke"
