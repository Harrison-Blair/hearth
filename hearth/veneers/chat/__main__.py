"""The chat veneer: a trivial stdin/stdout text client over the wire.

Runnable as the `hearth-chat` console script or `python -m hearth.veneers.chat`.
Reaches the engine only through `hearth.veneers.base` (connect / send_turn) and
reads only its own `config/chat.yaml` -- no engine internals.
"""
from __future__ import annotations

import asyncio
import sys

from hearth.veneers.base import EngineUnreachable, connect, send_turn
from hearth.veneers.chat.config import ChatSettings


def _print_message(message: dict) -> None:
    if message["type"] == "tool_activity":
        print(f"…{message['label']}")
    elif message["type"] == "answer":
        print(f"[\033[31mhearth\033[0m] {message['text']}")
    elif message["type"] == "error":
        print(f"error: {message['message']}")


async def _read_line() -> str:
    """Read one line of stdin without blocking the event loop, so keepalive
    pongs keep flowing while the user is idle at the prompt."""
    return await asyncio.to_thread(sys.stdin.readline)


async def run_client(host: str, port: int) -> None:
    async with connect(host, port) as websocket:
        while True:
            print("> ", end="", flush=True)
            line = await _read_line()
            if not line:  # EOF
                break
            line = line.strip()
            if not line:
                continue
            # The chat veneer declares its surface identity here, in one place.
            for message in await send_turn(websocket, line, "chat"):
                _print_message(message)


def main() -> int:
    settings = ChatSettings()
    try:
        asyncio.run(run_client(settings.engine.host, settings.engine.port))
    except EngineUnreachable as exc:
        # Fail fast at a terminal: a plain message, non-zero exit, no traceback.
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
