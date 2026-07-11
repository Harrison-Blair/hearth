"""Veneer: localhost WebSocket server driving `Loop.run_turn` per inbound turn.

A generic forwarder of the typed `hearth.events` union -- it never sees tool
query/arguments/observation/result content (see `protocol.serialize`).
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid

import websockets

from hearth.brain.errors import BrainError
from hearth.veneer.protocol import (
    answer_message,
    curate_error,
    done_message,
    error_message,
    parse_request,
    serialize,
)

logger = logging.getLogger(__name__)


class Veneer:
    def __init__(self, loop, log, config) -> None:
        self._loop = loop
        self._log = log
        self._config = config

    async def serve(self, host: str | None = None, port: int | None = None) -> None:
        host = host if host is not None else self._config.veneer.host
        port = port if port is not None else self._config.veneer.port
        async with websockets.serve(self._handle_connection, host, port):
            await asyncio.Future()  # run until cancelled

    async def _handle_connection(self, websocket) -> None:
        session_id = uuid.uuid4().hex
        # A client disconnecting mid-turn (awaiting run_turn or sending a
        # reply) raises ConnectionClosed; treat that as a clean end of this
        # connection rather than an unhandled exception out of the handler,
        # so websockets.serve keeps accepting other connections.
        try:
            # One turn at a time per connection: each inbound message is
            # awaited to completion (including all its emitted messages)
            # before the next is read off the socket.
            async for raw in websocket:
                # A frame that isn't valid JSON or lacks the request fields is
                # rejected on the wire (never echoing its content) and the
                # connection stays alive for the next frame.
                try:
                    request = parse_request(raw)
                except (json.JSONDecodeError, KeyError, TypeError):
                    logger.warning("rejecting malformed request frame for session %s", session_id)
                    self._log.append(
                        session_id, "", "error", "veneer", {"message": "malformed request"}
                    )
                    await websocket.send(json.dumps(error_message("", "malformed request")))
                    continue

                async def sink(event, _websocket=websocket) -> None:
                    await _websocket.send(json.dumps(serialize(event)))

                try:
                    answer_text = await self._loop.run_turn(
                        session_id, request.turn_id, request.final_user_transcript, emit=sink
                    )
                except websockets.ConnectionClosed:
                    raise
                except Exception as exc:
                    detail = exc.detail if isinstance(exc, BrainError) else str(exc)
                    self._log.append(
                        session_id, request.turn_id, "error", "loop", {"message": detail}
                    )
                    await websocket.send(
                        json.dumps(error_message(request.turn_id, curate_error(exc)))
                    )
                    continue

                await websocket.send(json.dumps(answer_message(request.turn_id, answer_text)))
                await websocket.send(json.dumps(done_message(request.turn_id)))
        except websockets.ConnectionClosed:
            logger.info("client disconnected mid-turn for session %s", session_id)
            return
