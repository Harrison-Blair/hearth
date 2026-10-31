"""WebSocket server: authentication, turn fan-out, history, and event logging."""

from __future__ import annotations

import asyncio
import contextlib
import traceback
from collections.abc import Callable
from datetime import datetime

from pydantic import ValidationError
from websockets.asyncio.server import Server, ServerConnection, serve
from websockets.exceptions import ConnectionClosed

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
    serialize,
)

from .clock import utc_now
from .config import BackendConfig, configured_api_keys
from .devices import DeviceError, DeviceStore
from .events import EventLog
from .history import History, Turn
from .llm import LLMClient
from .redaction import Redactor

_SAFE_LLM_ERROR = "The assistant is unavailable. Try again."


class Backend:
    """The running assistant backend."""

    def __init__(
        self,
        config: BackendConfig,
        devices: DeviceStore,
        llm: LLMClient,
        *,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._config = config
        self._devices = devices
        self._llm = llm
        self._clock = clock
        self._history = History(
            window_minutes=config.history.window_minutes,
            max_turns=config.history.max_turns,
            clock=clock,
        )
        self._events = EventLog(config.events.dir, clock=clock)
        self._redactor = Redactor(configured_api_keys(config))

    def serve(self) -> Server:
        """Return the websockets server, usable as an async context manager."""
        return serve(
            self._handle_connection,
            self._config.server.host,
            self._config.server.port,
        )

    async def _handle_connection(self, websocket: ServerConnection) -> None:
        authenticated = False
        device_id: str | None = None
        try:
            try:
                first = parse_client_message(await websocket.recv())
            except ValidationError:
                self._events.write("auth_rejected", device_id=None, reason="malformed")
                await websocket.close(CLOSE_BAD_MESSAGE, "expected hello")
                return

            if not isinstance(first, HelloMessage):
                self._events.write("auth_rejected", device_id=None, reason="expected hello")
                await websocket.close(CLOSE_BAD_MESSAGE, "expected hello")
                return

            device_id = first.device_id
            if first.protocol_version != PROTOCOL_VERSION:
                self._events.write("auth_rejected", device_id=device_id, reason="protocol_version")
                await websocket.close(CLOSE_BAD_MESSAGE, "unsupported protocol version")
                return

            try:
                authorized = self._devices.verify(device_id, first.token)
            except DeviceError:
                authorized = False
            if not authorized:
                self._events.write(
                    "auth_rejected", device_id=device_id, reason="invalid_credentials"
                )
                await websocket.close(CLOSE_UNAUTHORIZED, "authentication failed")
                return

            authenticated = True
            self._events.write("connected", device_id=device_id)

            tasks: set[asyncio.Task[None]] = set()
            try:
                async for raw in websocket:
                    try:
                        message = parse_client_message(raw)
                    except ValidationError:
                        await self._send_error(websocket, None, "bad_message", "Malformed message.")
                        continue
                    if not isinstance(message, UserTextMessage):
                        await self._send_error(
                            websocket, None, "bad_message", "Unexpected message."
                        )
                        continue
                    self._events.write(
                        "user_text",
                        device_id=device_id,
                        turn_id=message.turn_id,
                        text=message.text,
                    )
                    task = asyncio.create_task(self._run_turn(websocket, device_id, message))
                    tasks.add(task)
                    task.add_done_callback(tasks.discard)
            finally:
                for task in tasks:
                    task.cancel()
                if tasks:
                    await asyncio.gather(*tasks, return_exceptions=True)
        except ConnectionClosed:
            pass
        finally:
            if authenticated and device_id is not None:
                self._events.write("disconnected", device_id=device_id)

    async def _run_turn(
        self,
        websocket: ServerConnection,
        device_id: str,
        message: UserTextMessage,
    ) -> None:
        started_at = self._clock()
        context = self._history.context(device_id, message.text, now=started_at)
        pieces: list[str] = []
        try:
            async for piece in self._llm.stream(context):
                if not piece:
                    continue
                pieces.append(piece)
                await websocket.send(
                    serialize(ReplyDeltaMessage(turn_id=message.turn_id, text=piece))
                )
        except asyncio.CancelledError:
            raise
        except ConnectionClosed:
            return
        except Exception as exc:
            self._events.write(
                "llm_error",
                device_id=device_id,
                turn_id=message.turn_id,
                error=self._redactor.redact(f"{type(exc).__name__}: {exc}"),
                traceback=self._redactor.redact(traceback.format_exc()),
            )
            with contextlib.suppress(ConnectionClosed):
                await self._send_error(
                    websocket, message.turn_id, "llm_unavailable", _SAFE_LLM_ERROR
                )
            return

        try:
            await websocket.send(serialize(ReplyDoneMessage(turn_id=message.turn_id)))
        except ConnectionClosed:
            return

        self._history.append(
            Turn(
                device_id=device_id,
                user_text=message.text,
                reply_text="".join(pieces),
                timestamp=started_at,
            )
        )
        self._events.write(
            "reply",
            device_id=device_id,
            turn_id=message.turn_id,
            text="".join(pieces),
        )

    async def _send_error(
        self,
        websocket: ServerConnection,
        turn_id: str | None,
        code: str,
        message: str,
    ) -> None:
        await websocket.send(serialize(ErrorMessage(turn_id=turn_id, code=code, message=message)))
