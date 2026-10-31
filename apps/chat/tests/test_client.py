"""Chat client tests against a minimal protocol peer."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from websockets.asyncio.server import ServerConnection, serve

from hearth.chat import ChatClient
from hearth.protocol import (
    ErrorMessage,
    HelloMessage,
    ReplyDeltaMessage,
    UserTextMessage,
    parse_client_message,
    serialize,
)


@asynccontextmanager
async def _peer() -> AsyncIterator[tuple[str, list[str]]]:
    turns: list[str] = []

    async def handler(websocket: ServerConnection) -> None:
        hello = parse_client_message(await websocket.recv())
        assert isinstance(hello, HelloMessage)
        message = parse_client_message(await websocket.recv())
        assert isinstance(message, UserTextMessage)
        turns.append(message.turn_id)
        await websocket.send(serialize(ReplyDeltaMessage(turn_id=message.turn_id, text="partial ")))
        await websocket.send(
            serialize(
                ErrorMessage(
                    turn_id=message.turn_id,
                    code="llm_unavailable",
                    message="safe failure",
                )
            )
        )
        await websocket.wait_closed()

    async with serve(handler, "127.0.0.1", 0) as server:
        sockets = server.sockets
        assert sockets
        port = sockets[0].getsockname()[1]
        yield f"ws://127.0.0.1:{port}", turns


async def test_ask_returns_safe_error_with_partial_text() -> None:
    async with _peer() as (url, turns):
        pieces: list[str] = []
        async with ChatClient(url, "desk", "token") as client:
            result = await client.ask("hello", on_delta=pieces.append)

    assert turns == [result.turn_id]
    assert result.text == "partial "
    assert pieces == ["partial "]
    assert result.error_code == "llm_unavailable"
    assert result.error_message == "safe failure"
