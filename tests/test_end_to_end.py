"""Cross-package end-to-end test: real backend, real WebSocket, chat client."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from aiohttp import web

from hearth.backend.config import BackendConfig
from hearth.backend.devices import DeviceStore
from hearth.backend.llm import build_llm
from hearth.backend.server import Backend
from hearth.chat import ChatClient


def _sse(content: str | None, finish_reason: str | None = None) -> bytes:
    delta = {} if content is None else {"content": content}
    payload = {
        "id": "chatcmpl-stub",
        "object": "chat.completion.chunk",
        "created": 0,
        "model": "stub-model",
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
    }
    return f"data: {json.dumps(payload)}\n\n".encode()


@asynccontextmanager
async def _stub_llm(requests: list[dict[str, Any]]) -> AsyncIterator[str]:
    async def handler(request: web.Request) -> web.StreamResponse:
        body: dict[str, Any] = await request.json()
        requests.append(body)
        response = web.StreamResponse(status=200, headers={"Content-Type": "text/event-stream"})
        await response.prepare(request)
        for piece in ("Hello, ", "world!"):
            await response.write(_sse(piece))
        await response.write(_sse(None, finish_reason="stop"))
        await response.write(b"data: [DONE]\n\n")
        await response.write_eof()
        return response

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


async def test_chat_client_receives_streamed_reply_from_real_backend(
    tmp_path: Path,
) -> None:
    requests: list[dict[str, Any]] = []
    async with _stub_llm(requests) as base_url:
        store = DeviceStore(tmp_path / "config" / "devices.yaml")
        token = store.add("desk")
        config = BackendConfig.model_validate(
            {
                "server": {"host": "127.0.0.1", "port": 0},
                "providers": {"stub": {"base_url": base_url}},
                "roles": {"fast": {"provider": "stub", "model": "stub-model"}},
                "events": {"dir": str(tmp_path / "events")},
            }
        )
        llm = build_llm(config, "fast")
        backend = Backend(config, store, llm)
        try:
            async with backend.serve() as server:
                sockets = server.sockets
                assert sockets
                port = sockets[0].getsockname()[1]
                pieces: list[str] = []
                async with ChatClient(f"ws://127.0.0.1:{port}", "desk", token) as client:
                    result = await client.ask("hello there", on_delta=pieces.append)
        finally:
            await llm.aclose()

    assert result.error_code is None
    assert result.text == "Hello, world!"
    assert "".join(pieces) == "Hello, world!"
    assert len(result.turn_id) > 0
    assert requests[0]["messages"] == [{"role": "user", "content": "[desk] hello there"}]
