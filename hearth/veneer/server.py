"""Veneer: localhost WebSocket server driving `Loop.run_turn` per inbound turn.

A generic forwarder of the typed `hearth.events` union -- it never sees tool
query/arguments/observation/result content (see `protocol.serialize`).
"""
from __future__ import annotations

import asyncio
import json
import uuid

import websockets

from hearth.veneer.protocol import answer_message, done_message, error_message, parse_request, serialize


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
        # One turn at a time per connection: each inbound message is awaited
        # to completion (including all its emitted messages) before the next
        # is read off the socket.
        async for raw in websocket:
            request = parse_request(raw)

            async def sink(event, _websocket=websocket) -> None:
                await _websocket.send(json.dumps(serialize(event)))

            try:
                answer_text = await self._loop.run_turn(
                    session_id, request.turn_id, request.final_user_transcript, emit=sink
                )
            except Exception as exc:
                self._log.append(
                    session_id, request.turn_id, "error", "loop", {"message": str(exc)}
                )
                await websocket.send(
                    json.dumps(error_message(request.turn_id, "the turn failed"))
                )
                continue

            await websocket.send(json.dumps(answer_message(request.turn_id, answer_text)))
            await websocket.send(json.dumps(done_message(request.turn_id)))
