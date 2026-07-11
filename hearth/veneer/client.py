"""Trivial stdin/stdout text client for the veneer contract.

Small and dependency-light; `send_turn` is reused by the integration test.
"""
from __future__ import annotations

import asyncio
import json
import sys
import uuid

import websockets


async def send_turn(websocket, transcript: str) -> list[dict]:
    """Send one turn and return every inbound wire message, ending with the
    terminal `done`/`error`."""
    turn_id = uuid.uuid4().hex
    await websocket.send(json.dumps({"turn_id": turn_id, "final_user_transcript": transcript}))
    messages = []
    while True:
        raw = await websocket.recv()
        message = json.loads(raw)
        messages.append(message)
        if message["type"] in ("done", "error"):
            break
    return messages


def _print_message(message: dict) -> None:
    if message["type"] == "tool_activity":
        print(f"…{message['label']}")
    elif message["type"] == "answer":
        print(f"[\033[31mhearth\033[0m] {message['text']}")
    elif message["type"] == "error":
        print(f"error: {message['message']}")


async def run_client(host: str, port: int) -> None:
    uri = f"ws://{host}:{port}"
    async with websockets.connect(uri) as websocket:
        while True:
            print("> ", end="", flush=True)
            line = sys.stdin.readline()
            if not line:  # EOF
                break
            line = line.strip()
            if not line:
                continue
            for message in await send_turn(websocket, line):
                _print_message(message)


def main() -> None:
    from hearth.config import Settings

    settings = Settings()
    asyncio.run(run_client(settings.veneer.host, settings.veneer.port))


if __name__ == "__main__":
    main()
