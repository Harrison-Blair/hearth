"""Wire protocol model and parser tests."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from hearth.protocol import (
    CLOSE_BAD_MESSAGE,
    CLOSE_UNAUTHORIZED,
    PROTOCOL_VERSION,
    ErrorMessage,
    HelloMessage,
    ReplyDeltaMessage,
    ReplyDoneMessage,
    UserTextMessage,
    parse_client_message,
    parse_server_message,
    serialize,
)


def test_close_codes_and_version_are_stable() -> None:
    assert PROTOCOL_VERSION == 1
    assert CLOSE_BAD_MESSAGE == 4400
    assert CLOSE_UNAUTHORIZED == 4401


def test_hello_roundtrip() -> None:
    message = HelloMessage(device_id="desk", token="secret", protocol_version=1)

    parsed = parse_client_message(serialize(message))

    assert parsed == message
    assert json.loads(serialize(message))["type"] == "hello"


def test_user_text_roundtrip() -> None:
    message = UserTextMessage(turn_id="t1", text="hello")

    parsed = parse_client_message(serialize(message))

    assert parsed == message


def test_reply_delta_roundtrip() -> None:
    message = ReplyDeltaMessage(turn_id="t1", text="hel")

    parsed = parse_server_message(serialize(message))

    assert parsed == message


def test_reply_done_roundtrip() -> None:
    message = ReplyDoneMessage(turn_id="t1")

    parsed = parse_server_message(serialize(message))

    assert parsed == message


def test_error_roundtrip_with_and_without_turn_id() -> None:
    with_turn = ErrorMessage(turn_id="t1", code="llm_unavailable", message="try later")
    without_turn = ErrorMessage(turn_id=None, code="bad_message", message="malformed")

    assert parse_server_message(serialize(with_turn)) == with_turn
    assert parse_server_message(serialize(without_turn)) == without_turn


def test_client_parser_rejects_server_message() -> None:
    with pytest.raises(ValidationError):
        parse_client_message('{"type": "reply_done", "turn_id": "t1"}')


def test_server_parser_rejects_client_message() -> None:
    with pytest.raises(ValidationError):
        parse_server_message('{"type": "user_text", "turn_id": "t1", "text": "hi"}')


def test_unknown_type_is_rejected() -> None:
    with pytest.raises(ValidationError):
        parse_client_message('{"type": "unknown", "turn_id": "t1"}')


def test_malformed_json_is_rejected() -> None:
    with pytest.raises(ValidationError):
        parse_client_message("not json")


def test_extra_fields_are_rejected() -> None:
    with pytest.raises(ValidationError):
        parse_client_message('{"type": "user_text", "turn_id": "t1", "text": "hi", "extra": true}')
