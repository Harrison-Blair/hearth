"""Test support for backend integration tests."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from aiohttp import web
from websockets.asyncio.client import ClientConnection, connect

from hearth.backend.clock import utc_now
from hearth.backend.config import BackendConfig
from hearth.backend.devices import DeviceStore
from hearth.backend.llm import build_llm
from hearth.backend.server import Backend
from hearth.protocol import (
    ErrorMessage,
    HelloMessage,
    ReplyDeltaMessage,
    ReplyDoneMessage,
    UserTextMessage,
    parse_server_message,
    serialize,
)

StubHandler = Callable[[web.Request], Awaitable[web.StreamResponse]]


def sse_chunk(content: str | None, finish_reason: str | None = None) -> bytes:
    """Build one OpenAI chat.completion.chunk SSE event."""
    delta: dict[str, str] = {} if content is None else {"content": content}
    payload = {
        "id": "chatcmpl-stub",
        "object": "chat.completion.chunk",
        "created": 0,
        "model": "stub-model",
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
    }
    return f"data: {json.dumps(payload)}\n\n".encode()


async def write_sse(response: web.StreamResponse, pieces: list[str]) -> None:
    """Write a complete streamed chat completion to an aiohttp response."""
    for piece in pieces:
        await response.write(sse_chunk(piece))
    await response.write(sse_chunk(None, finish_reason="stop"))
    await response.write(b"data: [DONE]\n\n")
    await response.write_eof()


def stream_handler(
    pieces: list[str],
    *,
    requests: list[dict[str, Any]] | None = None,
) -> StubHandler:
    """Return a handler that streams ``pieces`` as an OpenAI-compatible reply."""

    async def handler(request: web.Request) -> web.StreamResponse:
        body: dict[str, Any] = await request.json()
        if requests is not None:
            requests.append(body)
        response = web.StreamResponse(status=200, headers={"Content-Type": "text/event-stream"})
        await response.prepare(request)
        await write_sse(response, pieces)
        return response

    return handler


@asynccontextmanager
async def stub_llm(handler: StubHandler) -> AsyncIterator[str]:
    """Run an in-process OpenAI-compatible HTTP server and yield its base URL."""
    app = web.Application()
    app.router.add_post("/v1/chat/completions", handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    try:
        host, port = runner.addresses[0][:2]
        yield f"http://{host}:{port}/v1"
    finally:
        await runner.cleanup()


@dataclass(frozen=True)
class RunningBackend:
    """A backend listening on a random local port."""

    url: str
    tokens: dict[str, str]
    events_dir: Path


@asynccontextmanager
async def running_backend(
    tmp_path: Path,
    base_url: str,
    *,
    device_ids: tuple[str, ...] = ("desk",),
    store: DeviceStore | None = None,
    clock: Callable[[], datetime] = utc_now,
) -> AsyncIterator[RunningBackend]:
    """Start a real backend against ``base_url`` on a random free port."""
    devices = store if store is not None else DeviceStore(tmp_path / "config" / "devices.yaml")
    tokens = {device_id: devices.add(device_id) for device_id in device_ids}
    events_dir = tmp_path / "events"
    config = BackendConfig.model_validate(
        {
            "server": {"host": "127.0.0.1", "port": 0},
            "providers": {"stub": {"base_url": base_url}},
            "roles": {"fast": {"provider": "stub", "model": "stub-model"}},
            "events": {"dir": str(events_dir)},
            "llm": {"timeout_s": 5},
        }
    )
    llm = build_llm(config, "fast")
    backend = Backend(config, devices, llm, clock=clock)
    try:
        async with backend.serve() as server:
            sockets = server.sockets
            assert sockets
            port = sockets[0].getsockname()[1]
            yield RunningBackend(
                url=f"ws://127.0.0.1:{port}",
                tokens=tokens,
                events_dir=events_dir,
            )
    finally:
        await llm.aclose()


async def send_hello(
    websocket: ClientConnection,
    device_id: str,
    token: str,
    *,
    protocol_version: int = 1,
) -> None:
    """Send a hello frame."""
    await websocket.send(
        serialize(
            HelloMessage(
                device_id=device_id,
                token=token,
                protocol_version=protocol_version,
            )
        )
    )


async def ask(websocket: ClientConnection, turn_id: str, text: str) -> str:
    """Send one user turn and return the joined reply deltas."""
    await websocket.send(serialize(UserTextMessage(turn_id=turn_id, text=text)))
    pieces: list[str] = []
    while True:
        message = parse_server_message(await asyncio.wait_for(websocket.recv(), timeout=10))
        if isinstance(message, ReplyDeltaMessage) and message.turn_id == turn_id:
            pieces.append(message.text)
        elif isinstance(message, ReplyDoneMessage) and message.turn_id == turn_id:
            return "".join(pieces)
        elif isinstance(message, ErrorMessage):
            raise AssertionError(f"turn failed: {message.code}: {message.message}")


async def open_authenticated(
    url: str,
    device_id: str,
    token: str,
) -> ClientConnection:
    """Open a WebSocket and complete hello authentication."""
    websocket = await connect(url)
    await send_hello(websocket, device_id, token)
    return websocket
