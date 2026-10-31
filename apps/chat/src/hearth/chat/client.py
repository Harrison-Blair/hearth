"""Importable chat client used by the REPL and by tests."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from types import TracebackType
from typing import Self

from websockets.asyncio.client import ClientConnection, connect

from hearth.protocol import (
    PROTOCOL_VERSION,
    ErrorMessage,
    HelloMessage,
    ReplyDeltaMessage,
    ReplyDoneMessage,
    UserTextMessage,
    parse_server_message,
    serialize,
)


class ChatClientError(Exception):
    """Raised when the client is used without a connection."""


@dataclass(frozen=True, slots=True)
class TurnResult:
    """The outcome of one user turn."""

    turn_id: str
    text: str
    error_code: str | None = None
    error_message: str | None = None


class ChatClient:
    """Send text turns to the backend and stream their replies."""

    def __init__(self, url: str, device_id: str, token: str) -> None:
        self._url = url
        self._device_id = device_id
        self._token = token
        self._connection: ClientConnection | None = None

    async def connect(self) -> None:
        """Open the WebSocket and send the hello frame."""
        connection = await connect(self._url)
        await connection.send(
            serialize(
                HelloMessage(
                    device_id=self._device_id,
                    token=self._token,
                    protocol_version=PROTOCOL_VERSION,
                )
            )
        )
        self._connection = connection

    async def close(self) -> None:
        """Close the connection if it is open."""
        connection = self._connection
        self._connection = None
        if connection is not None:
            await connection.close()

    async def __aenter__(self) -> Self:
        await self.connect()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.close()

    async def ask(
        self,
        text: str,
        on_delta: Callable[[str], None] | None = None,
    ) -> TurnResult:
        """Send one user turn and read until its reply is done or an error arrives."""
        connection = self._connection
        if connection is None:
            raise ChatClientError("client is not connected")

        turn_id = uuid.uuid4().hex
        await connection.send(serialize(UserTextMessage(turn_id=turn_id, text=text)))

        pieces: list[str] = []
        while True:
            message = parse_server_message(await connection.recv())
            if isinstance(message, ReplyDeltaMessage) and message.turn_id == turn_id:
                pieces.append(message.text)
                if on_delta is not None:
                    on_delta(message.text)
            elif isinstance(message, ReplyDoneMessage) and message.turn_id == turn_id:
                return TurnResult(turn_id=turn_id, text="".join(pieces))
            elif isinstance(message, ErrorMessage) and message.turn_id in (turn_id, None):
                return TurnResult(
                    turn_id=turn_id,
                    text="".join(pieces),
                    error_code=message.code,
                    error_message=message.message,
                )
