"""Concurrent turns, including an LLM that waits for the other turn."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from aiohttp import web
from helpers import (
    ask,
    open_authenticated,
    running_backend,
    stub_llm,
    write_sse,
)


async def test_concurrent_turns_do_not_wait_for_each_other(tmp_path: Path) -> None:
    slow_started = asyncio.Event()
    release_slow = asyncio.Event()
    requests: list[list[dict[str, Any]]] = []

    async def handler(request: web.Request) -> web.StreamResponse:
        body: dict[str, Any] = await request.json()
        messages: list[dict[str, Any]] = body["messages"]
        requests.append(messages)
        current = messages[-1]["content"]
        response = web.StreamResponse(status=200, headers={"Content-Type": "text/event-stream"})
        await response.prepare(request)
        if "slow" in current:
            slow_started.set()
            await asyncio.wait_for(release_slow.wait(), timeout=5)
            pieces = ["slow reply"]
        else:
            release_slow.set()
            pieces = ["fast reply"]
        await write_sse(response, pieces)
        return response

    async with (
        stub_llm(handler) as base_url,
        running_backend(tmp_path, base_url, device_ids=("A", "B")) as env,
        await open_authenticated(env.url, "A", env.tokens["A"]) as websocket_a,
        await open_authenticated(env.url, "B", env.tokens["B"]) as websocket_b,
    ):
        slow = asyncio.create_task(ask(websocket_a, "slow-1", "slow question"))
        await asyncio.wait_for(slow_started.wait(), timeout=5)
        fast = asyncio.create_task(ask(websocket_b, "fast-1", "fast question"))
        slow_reply, fast_reply = await asyncio.wait_for(asyncio.gather(slow, fast), timeout=10)

    assert slow_reply == "slow reply"
    assert fast_reply == "fast reply"
    assert len(requests) == 2
    for messages in requests:
        assert len(messages) == 1
