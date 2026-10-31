"""Connection authentication and close-code tests."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from helpers import ask, running_backend, send_hello, stream_handler, stub_llm
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed

from hearth.protocol import (
    CLOSE_BAD_MESSAGE,
    CLOSE_UNAUTHORIZED,
    HelloMessage,
    UserTextMessage,
    serialize,
)


async def _expect_close(url: str, frame: str, code: int) -> None:
    async with connect(url) as websocket:
        await websocket.send(frame)
        with pytest.raises(ConnectionClosed) as closed:
            await asyncio.wait_for(websocket.recv(), timeout=5)
    received = closed.value.rcvd
    assert received is not None
    assert received.code == code


async def test_wrong_token_closes_4401(tmp_path: Path) -> None:
    async with (
        stub_llm(stream_handler(["unused"])) as base_url,
        running_backend(tmp_path, base_url) as env,
    ):
        await _expect_close(
            env.url,
            serialize(HelloMessage(device_id="desk", token="wrong", protocol_version=1)),
            CLOSE_UNAUTHORIZED,
        )


async def test_rejected_auth_is_logged_without_the_token(tmp_path: Path) -> None:
    token = "super-secret-token"
    async with (
        stub_llm(stream_handler(["unused"])) as base_url,
        running_backend(tmp_path, base_url) as env,
    ):
        await _expect_close(
            env.url,
            serialize(HelloMessage(device_id="desk", token=token, protocol_version=1)),
            CLOSE_UNAUTHORIZED,
        )

        files = list(env.events_dir.glob("*.jsonl"))
        assert len(files) == 1
        raw = files[0].read_text(encoding="utf-8")
        records = [json.loads(line) for line in raw.splitlines()]

    assert [record["event"] for record in records] == ["auth_rejected"]
    assert records[0]["device_id"] == "desk"
    assert token not in raw


async def test_unknown_device_closes_4401(tmp_path: Path) -> None:
    async with (
        stub_llm(stream_handler(["unused"])) as base_url,
        running_backend(tmp_path, base_url) as env,
    ):
        await _expect_close(
            env.url,
            serialize(HelloMessage(device_id="missing", token="whatever", protocol_version=1)),
            CLOSE_UNAUTHORIZED,
        )


async def test_wrong_protocol_version_closes_4400(tmp_path: Path) -> None:
    async with (
        stub_llm(stream_handler(["unused"])) as base_url,
        running_backend(tmp_path, base_url) as env,
    ):
        await _expect_close(
            env.url,
            serialize(
                HelloMessage(
                    device_id="desk",
                    token=env.tokens["desk"],
                    protocol_version=2,
                )
            ),
            CLOSE_BAD_MESSAGE,
        )


async def test_first_message_not_hello_closes_4400(tmp_path: Path) -> None:
    async with (
        stub_llm(stream_handler(["unused"])) as base_url,
        running_backend(tmp_path, base_url) as env,
    ):
        await _expect_close(
            env.url,
            serialize(UserTextMessage(turn_id="t1", text="hi")),
            CLOSE_BAD_MESSAGE,
        )


async def test_malformed_first_message_closes_4400(tmp_path: Path) -> None:
    async with (
        stub_llm(stream_handler(["unused"])) as base_url,
        running_backend(tmp_path, base_url) as env,
    ):
        await _expect_close(env.url, "not json", CLOSE_BAD_MESSAGE)


async def test_hello_with_missing_fields_closes_4400(tmp_path: Path) -> None:
    async with (
        stub_llm(stream_handler(["unused"])) as base_url,
        running_backend(tmp_path, base_url) as env,
    ):
        await _expect_close(env.url, json.dumps({"type": "hello"}), CLOSE_BAD_MESSAGE)


async def test_valid_hello_is_accepted(tmp_path: Path) -> None:
    async with (
        stub_llm(stream_handler(["ok"])) as base_url,
        running_backend(tmp_path, base_url) as env,
        connect(env.url) as websocket,
    ):
        await send_hello(websocket, "desk", env.tokens["desk"])
        assert await ask(websocket, "t1", "hi") == "ok"
