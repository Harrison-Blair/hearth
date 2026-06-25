from assistant.nlu.keyphrase_router import KeyphraseRouter


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
