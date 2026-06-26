import logging

from assistant.app import _validate_routing
from assistant.nlu.keyphrase_router import KeyphraseRouter
from assistant.skills.base import Skill, SkillRegistry


def test_keyphrase_router_exposes_registered_intents():
    router = KeyphraseRouter()
    router.add("time", "what time")
    router.add("timer", "set a timer", "timer for")
    assert router.intents == {"time", "timer"}


class _Stub(Skill):
    def __init__(self, name, intents):
        self.name = name
        self.intents = intents

    async def handle(self, cmd, intent):  # pragma: no cover - not exercised here
        ...


def test_validate_routing_warns_on_missing_keyphrase(caplog):
    intents = {"time": "clock", "general": "fallback"}
    keyphrases = KeyphraseRouter(default_intent="general")  # no keyphrase for "time"
    registry = SkillRegistry()
    registry.register(_Stub("clock", {"time"}))
    registry.register(_Stub("general", {"general"}), default=True)

    with caplog.at_level(logging.WARNING, logger="assistant"):
        _validate_routing(intents, keyphrases, registry)
    assert any("time" in r.getMessage() and "keyphrase" in r.getMessage() for r in caplog.records)


def test_validate_routing_silent_when_consistent(caplog):
    intents = {"time": "clock", "general": "fallback"}
    keyphrases = KeyphraseRouter(default_intent="general")
    keyphrases.add("time", "what time")
    registry = SkillRegistry()
    registry.register(_Stub("clock", {"time"}))
    registry.register(_Stub("general", {"general"}), default=True)

    with caplog.at_level(logging.WARNING, logger="assistant"):
        _validate_routing(intents, keyphrases, registry)
    assert caplog.records == []  # default "general" needs no keyphrase


async def test_falls_back_to_default_intent():
    intent = await KeyphraseRouter().route("what is the capital of France")
    assert intent.type == "general"
    assert intent.raw_text == "what is the capital of France"


async def test_keyphrase_match_is_case_insensitive():
    router = KeyphraseRouter()
    router.add("time", "what time")
    assert (await router.route("Hey, WHAT TIME is it?")).type == "time"


async def test_first_registered_match_wins():
    router = KeyphraseRouter()
    router.add("a", "foo")
    router.add("b", "bar")
    assert (await router.route("foo and bar")).type == "a"


async def test_reminder_keyphrases_disambiguate():
    router = KeyphraseRouter()
    router.add("timer", "set a timer", "set timer", "timer for")
    router.add("reminder", "remind me", "set a reminder")
    router.add("list_reminders", "my reminders", "any reminders", "have reminders")

    assert (await router.route("remind me in 5 minutes to stretch")).type == "reminder"
    assert (await router.route("set a timer for 5 minutes")).type == "timer"
    assert (await router.route("what are my reminders")).type == "list_reminders"
    assert (await router.route("do I have any reminders")).type == "list_reminders"


async def test_manage_reminders_disambiguate():
    # Mirror app.py order: create, then manage, then list.
    router = KeyphraseRouter()
    router.add("reminder", "remind me", "set a reminder")
    router.add("manage_reminders", "cancel", "clear", "delete", "forget", "remove",
               "change my", "change the", "update my", "reschedule", "move my", "rename")
    router.add("list_reminders", "my reminders", "any reminders", "have reminders")

    # "cancel my reminders" contains "my reminders" too, but manage is registered first.
    assert (await router.route("cancel my reminders")).type == "manage_reminders"
    # "remind me ..." wins for creation even when it mentions cancelling.
    assert (await router.route("remind me to cancel the call")).type == "reminder"
    assert (await router.route("reschedule the dentist")).type == "manage_reminders"
    assert (await router.route("what are my reminders")).type == "list_reminders"


async def test_web_search_keyphrases_route_and_preserve_others():
    # Mirror app.py registration order.
    router = KeyphraseRouter()
    router.add("reminder", "remind me", "set a reminder")
    router.add("list_reminders", "my reminders", "any reminders", "have reminders")
    router.add("web_search", "search the web", "search for", "look up", "look it up",
               "google", "what's the latest", "latest on")

    assert (await router.route("search the web for the weather")).type == "web_search"
    assert (await router.route("what's the latest on the election")).type == "web_search"
    assert (await router.route("look up the world cup score")).type == "web_search"
    # Existing intents still route; a bare question falls through to general.
    assert (await router.route("remind me to call mom")).type == "reminder"
    assert (await router.route("what is the capital of France")).type == "general"


async def test_clock_keyphrases_route_to_clock_intents():
    router = KeyphraseRouter()
    router.add("time", "what time", "the time")
    router.add("date", "what day", "what's the date", "the date", "today's date")

    assert (await router.route("hey what time is it")).type == "time"
    assert (await router.route("do you have the time")).type == "time"
    assert (await router.route("what's the date today")).type == "date"
    assert (await router.route("what day is it")).type == "date"
    # An unrelated question still falls through to the LLM.
    assert (await router.route("what is the capital of France")).type == "general"
