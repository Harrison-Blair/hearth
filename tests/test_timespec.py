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

    async def complete(self, prompt, *, system=None, json=False, label=""):
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


def test_parse_duration_compound_word_numbers():
    assert parse_duration("twenty five minutes") == 1500.0
    assert parse_duration("thirty two seconds") == 32.0
    assert parse_duration("forty-five minutes") == 2700.0
    # single-word and bare-digit paths stay intact
    assert parse_duration("five minutes") == 300.0
    assert parse_duration("in 30 seconds") == 30.0
    assert parse_duration("2 hours") == 7200.0


def test_humanize():
    assert humanize(30) == "in 30 seconds"
    assert humanize(60) == "in 1 minute"
    assert humanize(300) == "in 5 minutes"
    assert humanize(3600) == "in 1 hour"


async def test_relative_reminder_uses_regex_not_llm():
    llm = FakeLLM("{}")
    spec = await extract_reminder(
        "remind me in 30 seconds to brush my teeth", llm, NOW
    )
    assert spec.message == "brush my teeth"
    assert spec.due_at == NOW.timestamp() + 30
    assert spec.interval is None  # one-shot
    assert llm.calls == []  # regex path never touched the LLM


async def test_message_before_duration():
    spec = await extract_reminder(
        "remind me to call mom in 5 minutes", FakeLLM("{}"), NOW
    )
    assert spec.message == "call mom"
    assert spec.due_at == NOW.timestamp() + 300


async def test_recurring_every_uses_regex_not_llm():
    llm = FakeLLM("{}")
    spec = await extract_reminder("remind me every 15 minutes to stretch", llm, NOW)
    assert spec.message == "stretch"
    assert spec.interval == 900.0
    assert spec.due_at == NOW.timestamp() + 900  # first fire one interval out
    assert llm.calls == []  # regex path


async def test_recurring_every_message_after_cadence():
    spec = await extract_reminder("remind me to stretch every 15 minutes", FakeLLM("{}"), NOW)
    assert spec.message == "stretch"
    assert spec.interval == 900.0


async def test_recurring_every_without_count_means_one():
    spec = await extract_reminder("remind me every hour to drink water", FakeLLM("{}"), NOW)
    assert spec.message == "drink water"
    assert spec.interval == 3600.0


async def test_recurring_via_llm_with_clock_start():
    llm = FakeLLM(
        json.dumps(
            {"delay_seconds": None, "at_time": "09:00", "interval_seconds": 86400,
             "message": "take pills"}
        )
    )
    spec = await extract_reminder("remind me every day at 9 am to take pills", llm, NOW)
    assert spec.message == "take pills"
    assert spec.interval == 86400.0
    # First fire honours the clock start, then repeats every interval.
    assert spec.due_at == NOW.replace(hour=9, minute=0, second=0, microsecond=0).timestamp() + 86400


async def test_absolute_time_via_llm():
    llm = FakeLLM(json.dumps({"delay_seconds": None, "at_time": "17:00", "message": "call mom"}))
    spec = await extract_reminder("remind me at 5 pm to call mom", llm, NOW)
    assert spec.message == "call mom"
    assert spec.due_at == NOW.replace(hour=17, minute=0, second=0, microsecond=0).timestamp()
    assert spec.interval is None


async def test_embedded_duration_with_clock_time_defers_to_llm():
    # "10 minute" is part of the task, not the schedule: a clock time is present,
    # so the regex must not hijack it — the LLM resolves the 6 pm time instead.
    llm = FakeLLM(json.dumps({"delay_seconds": None, "at_time": "18:00", "message": "workout"}))
    spec = await extract_reminder(
        "remind me to do a 10 minute workout at 6 pm", llm, NOW
    )
    assert spec.message == "workout"
    assert spec.due_at == NOW.replace(hour=18, minute=0, second=0, microsecond=0).timestamp()
    assert llm.calls != []  # the clock time forced the LLM path


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


async def test_parse_management_coerces_numeric_target_index():
    # The model may return target_index as a string or float; both must resolve.
    for raw in ("2", 2.0):
        llm = FakeLLM(json.dumps({"action": "cancel", "target_index": raw}))
        action = await parse_management("cancel the second one", ["a", "b"], llm, NOW)
        assert action.target_index == 2


async def test_parse_management_bad_json_is_none_action():
    action = await parse_management("cancel something", ["call mom in 5 minutes"], FakeLLM("not json"), NOW)
    assert action.action == "none"
    assert action.target_index is None


async def test_parse_management_unknown_action_is_none():
    llm = FakeLLM(json.dumps({"action": "frobnicate", "target_index": 1}))
    action = await parse_management("do something weird", ["call mom in 5 minutes"], llm, NOW)
    assert action.action == "none"
