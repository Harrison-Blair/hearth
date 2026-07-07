from datetime import datetime, timedelta, timezone

from assistant.calendar.base import CalendarEvent
from assistant.calendar.blocklist import EventBlocklist
from assistant.storage.calendar_state import CalendarStateStore

TZ = timezone(timedelta(hours=-4))


def _event(title: str, description: str = "") -> CalendarEvent:
    return CalendarEvent(
        id="ev1",
        calendar_id="cal",
        title=title,
        start=datetime(2026, 7, 7, 15, 0, tzinfo=TZ),
        description=description,
    )


def _blocklist(tmp_path, config_patterns=(), hidden_tag="[hidden]"):
    store = CalendarStateStore(str(tmp_path / "state.db"))
    return EventBlocklist(
        store, config_patterns=list(config_patterns), hidden_tag=hidden_tag
    )


def test_config_pattern_blocks_matching_title(tmp_path):
    blocklist = _blocklist(tmp_path, config_patterns=["bedtime"])
    assert blocklist.is_blocked(_event("Bedtime"))
    assert not blocklist.is_blocked(_event("Dentist"))


def test_voice_pattern_blocks_and_unblocks(tmp_path):
    blocklist = _blocklist(tmp_path)
    assert not blocklist.is_blocked(_event("Wake up"))
    blocklist.block("wake up", created_at=100.0)
    assert blocklist.is_blocked(_event("Wake up"))
    assert blocklist.unblock("Wake Up") is True
    assert not blocklist.is_blocked(_event("Wake up"))
    assert blocklist.unblock("wake up") is False  # already gone


def test_matching_is_substring_and_strips_emoji(tmp_path):
    blocklist = _blocklist(tmp_path, config_patterns=["bedtime", "Review I.M.T."])
    assert blocklist.is_blocked(_event("🛏️ Bedtime"))
    assert blocklist.is_blocked(_event("👁️‍🗨️ Review I.M.T."))
    assert blocklist.is_blocked(_event("early bedtime tonight"))


def test_hidden_tag_in_description_blocks(tmp_path):
    blocklist = _blocklist(tmp_path)
    assert blocklist.is_blocked(_event("Dentist", description="routine [HIDDEN] visit"))
    assert not blocklist.is_blocked(_event("Dentist", description="routine visit"))


def test_patterns_merges_store_and_config_without_duplicates(tmp_path):
    blocklist = _blocklist(tmp_path, config_patterns=["bedtime", "wake up"])
    blocklist.block("gym", created_at=100.0)
    blocklist.block("bedtime", created_at=200.0)  # also in config
    assert blocklist.patterns() == ["gym", "bedtime", "wake up"]


def test_in_config(tmp_path):
    blocklist = _blocklist(tmp_path, config_patterns=["bedtime"])
    assert blocklist.in_config("bedtime")
    assert blocklist.in_config("my bedtime routine")  # config pattern within it
    assert not blocklist.in_config("gym")
