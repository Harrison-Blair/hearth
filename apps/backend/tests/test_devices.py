"""Device commands and token verification."""

from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from helpers import ask, open_authenticated, running_backend, stream_handler, stub_llm
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed

from hearth.backend.devices import DeviceStore
from hearth.protocol import CLOSE_UNAUTHORIZED, HelloMessage, serialize


def _run_cli(tmp_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "hearth.backend", *args],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )


def test_serve_without_config_fails_clearly(tmp_path: Path) -> None:
    result = _run_cli(tmp_path, "serve")

    assert result.returncode != 0
    assert "config file not found" in result.stderr


async def test_add_device_stores_hash_and_remove_rejects_token(tmp_path: Path) -> None:
    added = _run_cli(tmp_path, "add-device", "desk")
    assert added.returncode == 0, added.stderr
    token = added.stdout.strip()
    assert token

    devices_path = tmp_path / "config" / "devices.yaml"
    raw = devices_path.read_text(encoding="utf-8")
    stored = yaml.safe_load(raw)
    assert token not in raw
    assert stored == {"desk": hashlib.sha256(token.encode()).hexdigest()}

    duplicate = _run_cli(tmp_path, "add-device", "desk")
    assert duplicate.returncode != 0
    assert "already exists" in duplicate.stderr

    async with (
        stub_llm(stream_handler(["welcome"])) as base_url,
        running_backend(
            tmp_path,
            base_url,
            device_ids=(),
            store=DeviceStore(devices_path),
        ) as env,
    ):
        async with await open_authenticated(env.url, "desk", token) as websocket:
            assert await ask(websocket, "t1", "hello") == "welcome"

        removed = _run_cli(tmp_path, "remove-device", "desk")
        assert removed.returncode == 0, removed.stderr
        assert yaml.safe_load(devices_path.read_text(encoding="utf-8")) == {}

        async with connect(env.url) as websocket:
            await websocket.send(
                serialize(HelloMessage(device_id="desk", token=token, protocol_version=1))
            )
            with pytest.raises(ConnectionClosed) as closed:
                await websocket.recv()
        received = closed.value.rcvd
        assert received is not None
        assert received.code == CLOSE_UNAUTHORIZED

    assert "desk" not in devices_path.read_text(encoding="utf-8")
    missing = _run_cli(tmp_path, "remove-device", "desk")
    assert missing.returncode != 0
    assert "does not exist" in missing.stderr
