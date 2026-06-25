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
