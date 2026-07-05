from assistant.core.events import Intent
from assistant.nlu.command_router import CommandEntryRouter
from assistant.skills.base import Skill, SkillRegistry


class _FakeSkill(Skill):
    def __init__(self, name, intents):
        self.name = name
        self.intents = intents

    async def handle(self, cmd, intent):
        ...


class _FakeRouter:
    def __init__(self):
        self.calls = []

    async def route(self, text):
        self.calls.append(text)
        return Intent(type="fallback", raw_text=text)


def _registry(*intents):
    reg = SkillRegistry()
    for i in intents:
        reg.register(_FakeSkill(i, {i}))
    return reg


def _router(registry, keyphrase="tool", aliases=None, next_router=None):
    fallback = next_router or _FakeRouter()
    return CommandEntryRouter(keyphrase, registry, fallback, aliases), fallback


async def test_no_keyphrase_delegates():
    registry = _registry("timer", "web_search")
    router, fallback = _router(registry)
    intent = await router.route("hello there")
    assert intent.type == "fallback"
    assert fallback.calls == ["hello there"]


async def test_keyphrase_match_routes_to_intent():
    registry = _registry("timer", "web_search")
    router, fallback = _router(registry)
    intent = await router.route("tool timer")
    assert intent.type == "timer"
    assert fallback.calls == []


async def test_keyphrase_with_args_passes_raw_text():
    registry = _registry("timer", "web_search")
    router, fallback = _router(registry)
    intent = await router.route("tool timer 5 minutes")
    assert intent.type == "timer"
    assert intent.raw_text == "5 minutes"
    assert fallback.calls == []


async def test_keyphrase_case_insensitive():
    registry = _registry("timer")
    router, fallback = _router(registry)
    intent = await router.route("TOOL timer 5 min")
    assert intent.type == "timer"
    assert fallback.calls == []


async def test_unknown_tool_falls_through():
    registry = _registry("timer", "web_search")
    router, fallback = _router(registry)
    intent = await router.route("tool bogus stuff")
    assert intent.type == "fallback"
    assert fallback.calls == ["tool bogus stuff"]


async def test_keyphrase_only_no_tool_falls_through():
    registry = _registry("timer")
    router, fallback = _router(registry)
    intent = await router.route("tool")
    assert intent.type == "fallback"
    assert fallback.calls == ["tool"]


async def test_keyphrase_with_only_spaces_falls_through():
    registry = _registry("timer")
    router, fallback = _router(registry)
    intent = await router.route("tool  ")
    assert intent.type == "fallback"
    assert fallback.calls == ["tool  "]


async def test_substring_not_triggered():
    registry = _registry("timer")
    router, fallback = _router(registry)
    intent = await router.route("toolbox timer")
    assert intent.type == "fallback"
    assert fallback.calls == ["toolbox timer"]


async def test_alias_resolves_to_intent():
    registry = _registry("time", "web_search")
    router, fallback = _router(registry, aliases={"clock": "time"})
    intent = await router.route("tool clock")
    assert intent.type == "time"
    assert fallback.calls == []


async def test_unknown_alias_falls_through():
    registry = _registry("time")
    router, fallback = _router(registry, aliases={"clock": "time"})
    intent = await router.route("tool nope")
    assert intent.type == "fallback"
    assert fallback.calls == ["tool nope"]


async def test_alias_with_args():
    registry = _registry("time", "web_search")
    router, fallback = _router(registry, aliases={"clock": "time"})
    intent = await router.route("tool clock what time is it")
    assert intent.type == "time"
    assert intent.raw_text == "what time is it"
    assert fallback.calls == []


async def test_custom_keyphrase():
    registry = _registry("timer")
    router, fallback = _router(registry, keyphrase="run")
    intent = await router.route("run timer 10 minutes")
    assert intent.type == "timer"
    assert fallback.calls == []


async def test_custom_keyphrase_no_match():
    registry = _registry("timer")
    router, fallback = _router(registry, keyphrase="run")
    intent = await router.route("tool timer 10 minutes")
    assert intent.type == "fallback"
    assert fallback.calls == ["tool timer 10 minutes"]
