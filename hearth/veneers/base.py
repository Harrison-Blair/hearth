"""The veneer client contract: what any surface needs to reach the engine.

A veneer is a separate process that talks to the engine only over the wire.
This module holds the three things every surface does -- connect to an engine
at a host/port, submit a turn and collect inbound messages until the terminal
`done`/`error`, and fail fast when the engine is unreachable -- and nothing
else. The audio plumages are further implementations of the same contract; it
is deliberately shaped around what `chat` demonstrably uses, so those widen it
when they exist, with a real second caller to shape it.

Imports only stdlib and `websockets`: no `hearth` engine internals ever cross
into a veneer.
"""
from __future__ import annotations

import json
import uuid
from contextlib import asynccontextmanager

import websockets


class EngineUnreachable(Exception):
    """The engine could not be reached at the configured host/port.

    Carries a plain, terminal-friendly message (no traceback for the surface
    to print) naming where it tried and that the engine may not be running.
    """

    def __init__(self, host: str, port: int) -> None:
        self.host = host
        self.port = port
        super().__init__(
            f"cannot reach the hearth engine at {host}:{port} -- "
            "is it running? start it with `hearth run`."
        )


@asynccontextmanager
async def connect(host: str, port: int):
    """Open a connection to the engine, failing fast if it is unreachable.

    A refused/failed connection is reported as `EngineUnreachable` -- a clean
    message the surface can print without a stack trace -- rather than letting
    `websockets.connect` raise an OSError up through the terminal. Unattended
    surfaces (the audio plumages, PLM-008 FC-10) add retry; chat, at a
    terminal, deliberately does not.
    """
    try:
        connection = await websockets.connect(f"ws://{host}:{port}")
    except OSError as exc:
        raise EngineUnreachable(host, port) from exc
    try:
        yield connection
    finally:
        await connection.close()


async def send_turn(websocket, transcript: str, surface: str) -> list[dict]:
    """Send one turn and return every inbound wire message, ending with the
    terminal `done`/`error`.

    `surface` is the caller's self-declared identity (`chat`, `audio`, ...),
    sent with every turn so the engine can attribute the logged turn to its
    originating surface. It has no default: each surface names itself once at
    its call site, so a new surface declares its identity without touching this
    contract or the engine (FTHR-025 FC-8)."""
    turn_id = uuid.uuid4().hex
    await websocket.send(
        json.dumps(
            {"turn_id": turn_id, "final_user_transcript": transcript, "surface": surface}
        )
    )
    messages = []
    while True:
        raw = await websocket.recv()
        message = json.loads(raw)
        messages.append(message)
        if message["type"] in ("done", "error"):
            break
    return messages
