import json
from datetime import datetime

from assistant.nlu.timespec import (
    extract_reminder,
    humanize,
    parse_duration,
    parse_management,
    resolve_time,
)

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


def test_resolve_time_delay_and_clock():
    assert resolve_time(NOW, delay_seconds=300, at_time=None) == NOW.timestamp() + 300
    clock = resolve_time(NOW, delay_seconds=None, at_time="17:00")
    assert clock == NOW.replace(hour=17, minute=0, second=0, microsecond=0).timestamp()
    assert resolve_time(NOW, delay_seconds=None, at_time=None) is None
    assert resolve_time(NOW, delay_seconds=0, at_time=None) is None


async def test_parse_management_maps_canned_json():
    llm = FakeLLM(
        json.dumps(
            {
                "action": "reschedule",
                "target_index": 2,
                "new_delay_seconds": None,
                "new_at_time": "18:00",
                "new_message": None,
            }
        )
    )
    action = await parse_management(
        "move my call-mom reminder to 6 pm", ["a timer in 1 minute", "call mom in 5 minutes"], llm, NOW
    )
    assert action.action == "reschedule"
    assert action.target_index == 2
    assert action.new_at_time == "18:00"
    # The pending list is embedded in the prompt so the LLM can resolve the target.
    assert "1. a timer in 1 minute" in llm.calls[0]
    assert "2. call mom in 5 minutes" in llm.calls[0]


async def test_parse_management_bad_json_is_none_action():
    action = await parse_management("cancel something", ["call mom in 5 minutes"], FakeLLM("not json"), NOW)
    assert action.action == "none"
    assert action.target_index is None


async def test_parse_management_unknown_action_is_none():
    llm = FakeLLM(json.dumps({"action": "frobnicate", "target_index": 1}))
    action = await parse_management("do something weird", ["call mom in 5 minutes"], llm, NOW)
    assert action.action == "none"
