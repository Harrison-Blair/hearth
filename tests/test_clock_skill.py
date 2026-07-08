from datetime import datetime

from assistant.core.events import Command, Intent
from assistant.skills.clock import ClockSkill, _ordinal


def _clock_at(dt):
    return ClockSkill(now=lambda: dt)


async def test_time_is_spoken_12_hour():
    res = await _clock_at(datetime(2026, 6, 25, 15, 42)).handle(
        Command("what time is it"), Intent("time")
    )
    assert res.speech == "It's 3:42 PM."
    assert res.data == {"time": "15:42"}


async def test_date_is_spoken_with_ordinal():
    dt = datetime(2026, 6, 25, 15, 42)
    res = await _clock_at(dt).handle(Command("what's the date"), Intent("date"))
    assert res.speech == f"Today is {dt:%A, %B} 25th."
    assert res.data == {"date": "2026-06-25", "weekday": "Thursday"}


def test_date_description_excludes_todays_events():
    desc = ClockSkill.tool_specs["date"]["description"]
    assert "not for events, schedules, or news" in desc


def test_ordinal_suffixes():
    assert [_ordinal(n) for n in (1, 2, 3, 4, 11, 12, 13, 21, 22, 23, 31)] == [
        "1st", "2nd", "3rd", "4th", "11th", "12th", "13th", "21st", "22nd", "23rd", "31st",
    ]
