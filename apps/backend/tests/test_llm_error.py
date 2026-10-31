"""LLM failure handling."""

from __future__ import annotations

import json
from pathlib import Path

from aiohttp import web
from helpers import (
    ask,
    open_authenticated,
    running_backend,
    stub_llm,
    write_sse,
)
from websockets.asyncio.client import ClientConnection

from hearth.protocol import (
    ErrorMessage,
    ReplyDoneMessage,
    UserTextMessage,
    parse_server_message,
    serialize,
)


async def _ask_for_error(websocket: ClientConnection, turn_id: str, text: str) -> ErrorMessage:
    await websocket.send(serialize(UserTextMessage(turn_id=turn_id, text=text)))
    while True:
        message = parse_server_message(await websocket.recv())
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

        assert await ask(websocket, "second", "second") == "recovered"

    files = list(env.events_dir.glob("*.jsonl"))
    assert len(files) == 1
    records = [json.loads(line) for line in files[0].read_text(encoding="utf-8").splitlines()]
    llm_errors = [record for record in records if record["event"] == "llm_error"]
    assert len(llm_errors) == 1
    assert llm_errors[0]["device_id"] == "desk"
    assert llm_errors[0]["turn_id"] == first.turn_id
    assert llm_errors[0]["error"]
    assert "BadRequestError" in llm_errors[0]["error"]
