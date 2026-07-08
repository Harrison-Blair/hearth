from datetime import datetime, timedelta, timezone

from assistant.calendar.extraction import (
    extract_event,
    parse_block_request,
    parse_event_management,
    parse_event_reminder,
    resolve_start,
)

TZ = timezone(timedelta(hours=-4))
NOW = datetime(2026, 7, 6, 10, 0, tzinfo=TZ)  # Monday morning


class FakeLLM:
    def __init__(self, reply: str):
        self.reply = reply
        self.prompts: list[str] = []

    async def complete(self, prompt, json=False, label=None):
        self.prompts.append(prompt)
        return self.reply


async def test_extract_event_with_date_and_duration():
    llm = FakeLLM(
        '{"title": "dentist appointment", "date": "2026-07-07", '
        '"start_time": "15:00", "duration_minutes": 30}'
    )
    event = await extract_event("add a dentist appointment tuesday at 3", llm, NOW)
    assert event.title == "dentist appointment"
    assert event.start == datetime(2026, 7, 7, 15, 0, tzinfo=TZ)
    assert event.end == datetime(2026, 7, 7, 15, 30, tzinfo=TZ)


async def test_extract_event_null_duration_defaults_to_an_hour():
    llm = FakeLLM(
        '{"title": "lunch", "date": "2026-07-07", "start_time": "12:00", '
        '"duration_minutes": null}'
    )
    event = await extract_event("lunch tuesday at noon", llm, NOW)
    assert event.end - event.start == timedelta(minutes=60)


async def test_extract_event_null_date_rolls_past_times_to_tomorrow():
    llm = FakeLLM('{"title": "standup", "date": null, "start_time": "09:00", "duration_minutes": null}')
    event = await extract_event("standup at 9", llm, NOW)  # 9:00 already passed at 10:00
    assert event.start == datetime(2026, 7, 7, 9, 0, tzinfo=TZ)


async def test_extract_event_null_date_keeps_future_times_today():
    llm = FakeLLM('{"title": "call", "date": null, "start_time": "16:00", "duration_minutes": null}')
    event = await extract_event("call at 4", llm, NOW)
    assert event.start == datetime(2026, 7, 6, 16, 0, tzinfo=TZ)


async def test_extract_event_malformed_json_returns_none():
    assert await extract_event("gibberish", FakeLLM("not json"), NOW) is None


async def test_extract_event_missing_title_returns_none():
    llm = FakeLLM('{"title": "", "date": null, "start_time": "16:00", "duration_minutes": null}')
    assert await extract_event("something at 4", llm, NOW) is None


async def test_extract_event_missing_time_returns_none():
    llm = FakeLLM('{"title": "party", "date": "2026-07-07", "start_time": null, "duration_minutes": null}')
    assert await extract_event("party tuesday", llm, NOW) is None


def test_resolve_start_rejects_bad_date():
    assert resolve_start(NOW, "not-a-date", "15:00") is None


async def test_parse_event_management_cancel_with_string_index():
    llm = FakeLLM('{"action": "cancel", "target_index": "2", "new_date": null, '
                  '"new_start_time": null, "new_title": null}')
    action = await parse_event_management("cancel the gym one", ["dentist", "gym"], llm, NOW)
    assert action.action == "cancel"
    assert action.target_index == 2
    assert "1. dentist" in llm.prompts[0]
    assert "2. gym" in llm.prompts[0]


async def test_parse_event_management_reschedule_carries_new_time():
    llm = FakeLLM('{"action": "reschedule", "target_index": 1, "new_date": null, '
                  '"new_start_time": "16:00", "new_title": null}')
    action = await parse_event_management("move it to 4", ["dentist"], llm, NOW)
    assert action.action == "reschedule"
    assert action.new_start_time == "16:00"


async def test_parse_event_management_bad_action_is_none():
    llm = FakeLLM('{"action": "explode", "target_index": 1}')
    action = await parse_event_management("do something", ["dentist"], llm, NOW)
    assert action.action == "none"


async def test_parse_event_management_malformed_json_is_none():
    action = await parse_event_management("cancel it", ["dentist"], FakeLLM("nope"), NOW)
    assert action.action == "none"


async def test_parse_event_reminder_explicit_lead():
    llm = FakeLLM('{"target_index": 1, "lead_minutes": 30}')
    req = await parse_event_reminder("remind me 30 min before dentist", ["dentist"], llm, NOW)
    assert req.target_index == 1
    assert req.lead_minutes == 30


async def test_parse_event_reminder_defaults_lead_to_15():
    llm = FakeLLM('{"target_index": 1, "lead_minutes": null}')
    req = await parse_event_reminder("remind me before dentist", ["dentist"], llm, NOW)
    assert req.lead_minutes == 15


async def test_parse_event_reminder_malformed_json_has_no_target():
    req = await parse_event_reminder("remind me", ["dentist"], FakeLLM("nope"), NOW)
    assert req.target_index is None


async def test_parse_block_request_block():
    llm = FakeLLM('{"action": "block", "pattern": "bedtime"}')
    req = await parse_block_request("stop bringing up bedtime", llm)
    assert req.action == "block"
    assert req.pattern == "bedtime"


async def test_parse_block_request_list_has_no_pattern():
    llm = FakeLLM('{"action": "list", "pattern": null}')
    req = await parse_block_request("what events are you ignoring", llm)
    assert req.action == "list"
    assert req.pattern is None


async def test_parse_block_request_blank_pattern_is_none():
    llm = FakeLLM('{"action": "unblock", "pattern": "  "}')
    req = await parse_block_request("mention it again", llm)
    assert req.action == "unblock"
    assert req.pattern is None


async def test_parse_block_request_bad_action_is_none():
    llm = FakeLLM('{"action": "explode", "pattern": "bedtime"}')
    req = await parse_block_request("do something", llm)
    assert req.action == "none"


async def test_parse_block_request_malformed_json_is_none():
    req = await parse_block_request("stop it", FakeLLM("nope"))
    assert req.action == "none"
