"""Console client shutdown behavior."""

from __future__ import annotations

import asyncio
import os
import pty
import select
import signal
import subprocess
import sys
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from websockets.asyncio.server import ServerConnection, serve


@asynccontextmanager
async def _accepting_backend() -> AsyncIterator[str]:
    async def handler(websocket: ServerConnection) -> None:
        await websocket.recv()
        await websocket.wait_closed()

    async with serve(handler, "127.0.0.1", 0) as server:
        sockets = server.sockets
        assert sockets
        port = sockets[0].getsockname()[1]
        yield f"ws://127.0.0.1:{port}"


def _read_until(fd: int, marker: bytes, timeout: float) -> bytes:
    data = b""
    deadline = time.monotonic() + timeout
    while marker not in data:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise AssertionError(f"did not see {marker!r}; output was {data!r}")
        ready, _, _ = select.select([fd], [], [], remaining)
        if not ready:
            raise AssertionError(f"did not see {marker!r}; output was {data!r}")
        chunk = os.read(fd, 1024)
        if not chunk:
            raise AssertionError(f"chat exited before {marker!r}; output was {data!r}")
        data += chunk
    return data


async def test_ctrl_c_at_prompt_exits_without_another_line(tmp_path: Path) -> None:
    async with _accepting_backend() as backend_url:
        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "chat.yaml").write_text(
            f"backend_url: {backend_url}\ndevice_id: desk\ntoken: token\n",
            encoding="utf-8",
        )

        master, slave = pty.openpty()
        process = subprocess.Popen(
            [sys.executable, "-m", "hearth.chat"],
            cwd=tmp_path,
            stdin=slave,
            stdout=slave,
            stderr=slave,
            close_fds=True,
        )
        os.close(slave)
        try:
            await asyncio.to_thread(_read_until, master, b"> ", 5)
            process.send_signal(signal.SIGINT)
            for _ in range(30):
                if process.poll() is not None:
                    break
                await asyncio.sleep(0.1)
            else:
                process.kill()
                raise AssertionError("hearth-chat did not exit after Ctrl-C")
            assert process.returncode == 0
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
            os.close(master)
