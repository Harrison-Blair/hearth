"""History snapshot, window, and turn-limit tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from hearth.backend.history import History, Turn

NOW = datetime(2025, 1, 1, 12, 0, tzinfo=UTC)


def _turn(device_id: str, text: str, minutes_ago: int) -> Turn:
    return Turn(
        device_id=device_id,
        user_text=text,
        reply_text=f"reply to {text}",
        timestamp=NOW - timedelta(minutes=minutes_ago),
    )


def test_context_tags_prior_turns_and_current_room() -> None:
    history = History(window_minutes=10, max_turns=20, clock=lambda: NOW)
    history.append(_turn("A", "kitchen lights on", 1))

    messages = history.context("B", "what did A say?", now=NOW)

    assert messages == [
        {"role": "user", "content": "[A] kitchen lights on"},
        {"role": "assistant", "content": "reply to kitchen lights on"},
        {"role": "user", "content": "[B] what did A say?"},
    ]


def test_context_excludes_turns_older_than_window() -> None:
    history = History(window_minutes=10, max_turns=20, clock=lambda: NOW)
    history.append(_turn("A", "too old", 12))
    history.append(_turn("A", "recent", 5))

    messages = history.context("B", "now", now=NOW)

    contents = [message["content"] for message in messages]
    assert "[A] too old" not in contents
    assert "[A] recent" in contents


def test_context_excludes_turn_exactly_at_window_boundary() -> None:
    history = History(window_minutes=10, max_turns=20, clock=lambda: NOW)
    history.append(_turn("A", "boundary", 10))

    messages = history.context("B", "now", now=NOW)

    assert messages == [{"role": "user", "content": "[B] now"}]


def test_context_keeps_only_last_max_turns() -> None:
    history = History(window_minutes=10, max_turns=2, clock=lambda: NOW)
    history.append(_turn("A", "one", 4))
    history.append(_turn("A", "two", 3))
    history.append(_turn("A", "three", 2))

    messages = history.context("B", "now", now=NOW)

    contents = [message["content"] for message in messages]
    assert "[A] one" not in contents
    assert "[A] two" in contents
    assert "[A] three" in contents


def test_context_uses_injected_clock() -> None:
    history = History(window_minutes=10, max_turns=20, clock=lambda: NOW)
    history.append(_turn("A", "recent", 1))

    messages = history.context("B", "now")

    assert messages[0] == {"role": "user", "content": "[A] recent"}
