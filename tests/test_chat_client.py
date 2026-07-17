"""Regression tests for the chat text client and gateway keepalive.

Guards the fix for the "keepalive ping timeout" disconnect: the client must
read stdin off the event loop so keepalive pongs keep flowing while the user
idles at the prompt, and the gateway must not proactively kill an idle
localhost connection.
"""
from __future__ import annotations

import asyncio
import threading
import time

from hearth.gateway import server
from hearth.veneers.chat import __main__ as client


async def test_read_line_does_not_block_event_loop(monkeypatch):
    """`_read_line` must offload the blocking stdin read so a concurrent
    coroutine still runs while a line is pending. If the read blocks the loop
    (the bug), the sentinel below can't run to release it and the read stalls
    for the full timeout -- which this test rejects."""
    release = threading.Event()

    def blocking_readline() -> str:
        release.wait(2.0)  # self-releasing so a broken loop can't hang forever
        return "hello\n"

    monkeypatch.setattr(client.sys.stdin, "readline", blocking_readline)

    async def sentinel() -> None:
        # Runs only if the event loop is free while the read is pending.
        await asyncio.sleep(0.05)
        release.set()

    read_task = asyncio.create_task(client._read_line())
    sentinel_task = asyncio.create_task(sentinel())

    start = time.monotonic()
    result = await asyncio.wait_for(read_task, timeout=3.0)
    elapsed = time.monotonic() - start
    await sentinel_task

    assert result == "hello\n"
    # Fixed: the sentinel released the read in ~0.05s. Blocking: the loop was
    # frozen, the sentinel never ran, and the read waited the full 2.0s.
    assert elapsed < 1.0


async def test_serve_disables_keepalive(monkeypatch):
    """`Gateway.serve` must pass ping_interval=None so an idle localhost
    control connection isn't false-closed by the library's default 20s ping
    timeout."""
    captured = {}

    class _FakeServe:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    def fake_serve(handler, host, port, **kwargs):
        captured["kwargs"] = kwargs
        return _FakeServe()

    monkeypatch.setattr(server.websockets, "serve", fake_serve)

    gateway = server.Gateway(loop=None, log=None, config=None)
    serve_task = asyncio.create_task(gateway.serve(host="127.0.0.1", port=0))
    # Let serve() reach the `await asyncio.Future()` after opening the server.
    await asyncio.sleep(0.05)
    serve_task.cancel()
    try:
        await serve_task
    except asyncio.CancelledError:
        pass

    assert captured["kwargs"].get("ping_interval") is None
