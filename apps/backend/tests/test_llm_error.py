"""LLM failure handling."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

import pytest
from aiohttp import web
from helpers import (
    ask,
    open_authenticated,
    running_backend,
    sse_chunk,
    stub_llm,
    write_sse,
)
from websockets.asyncio.client import ClientConnection

from hearth.protocol import (
    ErrorMessage,
    ReplyDeltaMessage,
    ReplyDoneMessage,
    UserTextMessage,
    parse_server_message,
    serialize,
)


async def _ask_for_error(websocket: ClientConnection, turn_id: str, text: str) -> ErrorMessage:
    await websocket.send(serialize(UserTextMessage(turn_id=turn_id, text=text)))
    while True:
        message = parse_server_message(await asyncio.wait_for(websocket.recv(), timeout=5))
        if isinstance(message, ErrorMessage):
            return message
        if isinstance(message, ReplyDoneMessage):
            raise AssertionError("turn unexpectedly succeeded")


async def test_llm_error_reports_safe_error_and_serves_next_turn(tmp_path: Path) -> None:
    calls = 0

    async def handler(request: web.Request) -> web.StreamResponse:
        nonlocal calls
        calls += 1
        if calls == 1:
            return web.Response(status=400, text="stub LLM failure")
        response = web.StreamResponse(status=200, headers={"Content-Type": "text/event-stream"})
        await response.prepare(request)
        await write_sse(response, ["recovered"])
        return response

    async with (
        stub_llm(handler) as base_url,
        running_backend(tmp_path, base_url) as env,
        await open_authenticated(env.url, "desk", env.tokens["desk"]) as websocket,
    ):
        first = await _ask_for_error(websocket, "first", "first")
        assert first.code == "llm_unavailable"
        assert "400" not in first.message
        assert "BadRequestError" not in first.message
        assert "Traceback" not in first.message

        assert await ask(websocket, "second", "second") == "recovered"

    files = list(env.events_dir.glob("*.jsonl"))
    assert len(files) == 1
    records = [json.loads(line) for line in files[0].read_text(encoding="utf-8").splitlines()]
    llm_errors = [record for record in records if record["event"] == "llm_error"]
    assert len(llm_errors) == 1
    assert llm_errors[0]["device_id"] == "desk"
    assert llm_errors[0]["turn_id"] == first.turn_id
    assert llm_errors[0]["error"]
    assert llm_errors[0]["traceback"]
    assert "BadRequestError" in llm_errors[0]["error"]


async def test_upstream_error_redacts_configured_api_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    api_key = "sk-hearth-test-secret-0123456789"
    monkeypatch.setenv("HEARTH_TEST_API_KEY", api_key)
    caplog.set_level(logging.DEBUG)

    async def handler(request: web.Request) -> web.StreamResponse:
        authorization = request.headers.get("Authorization", "")
        return web.json_response(
            {"error": {"message": f"invalid authorization header: {authorization}"}},
            status=401,
        )

    async with (
        stub_llm(handler) as base_url,
        running_backend(
            tmp_path,
            base_url,
            api_key_env="HEARTH_TEST_API_KEY",
        ) as env,
        await open_authenticated(env.url, "desk", env.tokens["desk"]) as websocket,
    ):
        first = await _ask_for_error(websocket, "redact", "first")
        assert first.code == "llm_unavailable"
        assert api_key not in first.message

    captured = capsys.readouterr()
    assert api_key not in captured.out
    assert api_key not in captured.err
    assert api_key not in caplog.text

    files = list(env.events_dir.glob("*.jsonl"))
    assert len(files) == 1
    raw = files[0].read_text(encoding="utf-8")
    assert api_key not in raw

    records = [json.loads(line) for line in raw.splitlines()]
    llm_errors = [record for record in records if record["event"] == "llm_error"]
    assert len(llm_errors) == 1
    assert "401" in llm_errors[0]["error"]


async def test_truncated_stream_is_llm_error_and_next_turn_works(tmp_path: Path) -> None:
    calls = 0

    async def handler(request: web.Request) -> web.StreamResponse:
        nonlocal calls
        calls += 1
        response = web.StreamResponse(status=200, headers={"Content-Type": "text/event-stream"})
        await response.prepare(request)
        if calls == 1:
            await response.write(sse_chunk("partial"))
            await response.write_eof()
        else:
            await write_sse(response, ["recovered"])
        return response

    async with (
        stub_llm(handler) as base_url,
        running_backend(tmp_path, base_url) as env,
        await open_authenticated(env.url, "desk", env.tokens["desk"]) as websocket,
    ):
        first = await _ask_for_error(websocket, "truncated", "first")
        assert first.code == "llm_unavailable"

        await websocket.send(serialize(UserTextMessage(turn_id="next", text="second")))
        pieces: list[str] = []
        done_ids: list[str] = []
        while "next" not in done_ids:
            message = parse_server_message(await asyncio.wait_for(websocket.recv(), timeout=5))
            if isinstance(message, ReplyDeltaMessage) and message.turn_id == "next":
                pieces.append(message.text)
            elif isinstance(message, ReplyDoneMessage):
                done_ids.append(message.turn_id)
        assert done_ids == ["next"]
        assert "".join(pieces) == "recovered"

    files = list(env.events_dir.glob("*.jsonl"))
    assert len(files) == 1
    records = [json.loads(line) for line in files[0].read_text(encoding="utf-8").splitlines()]
    llm_errors = [record for record in records if record["event"] == "llm_error"]
    replies = [record for record in records if record["event"] == "reply"]
    assert len(llm_errors) == 1
    assert llm_errors[0]["turn_id"] == "truncated"
    assert [record["turn_id"] for record in replies] == ["next"]
