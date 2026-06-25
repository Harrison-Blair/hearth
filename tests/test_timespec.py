import json
from datetime import datetime

from assistant.nlu.timespec import extract_reminder, humanize, parse_duration

NOW = datetime(2026, 6, 25, 15, 0, 0).astimezone()


class FakeLLM:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    async def complete(self, prompt, *, system=None, json=False):
        self.calls.append(prompt)
        return self.payload

    async def health(self):
        return True


def test_parse_duration_digits_words_and_misses():
    assert parse_duration("set a timer for 30 seconds") == 30.0
    assert parse_duration("remind me in 5 minutes") == 300.0
    assert parse_duration("for five minutes") == 300.0
    assert parse_duration("2 hours") == 7200.0
    assert parse_duration("what time is it") is None


def test_humanize():
    assert humanize(30) == "in 30 seconds"
    assert humanize(60) == "in 1 minute"
    assert humanize(300) == "in 5 minutes"
    assert humanize(3600) == "in 1 hour"


async def test_relative_reminder_uses_regex_not_llm():
    llm = FakeLLM("{}")
    due, message = await extract_reminder(
        "remind me in 30 seconds to brush my teeth", llm, NOW
    )
    assert message == "brush my teeth"
    assert due == NOW.timestamp() + 30
    assert llm.calls == []  # regex path never touched the LLM


async def test_message_before_duration():
    due, message = await extract_reminder(
        "remind me to call mom in 5 minutes", FakeLLM("{}"), NOW
    )
    assert message == "call mom"
    assert due == NOW.timestamp() + 300


async def test_absolute_time_via_llm():
    llm = FakeLLM(json.dumps({"delay_seconds": None, "at_time": "17:00", "message": "call mom"}))
    due, message = await extract_reminder("remind me at 5 pm to call mom", llm, NOW)
    assert message == "call mom"
    assert due == NOW.replace(hour=17, minute=0, second=0, microsecond=0).timestamp()


async def test_none_on_bad_json():
    assert await extract_reminder("remind me to do a thing", FakeLLM("not json"), NOW) is None


async def test_none_when_no_time_found():
    llm = FakeLLM(json.dumps({"delay_seconds": None, "at_time": None, "message": "x"}))
    assert await extract_reminder("remind me to do a thing", llm, NOW) is None
