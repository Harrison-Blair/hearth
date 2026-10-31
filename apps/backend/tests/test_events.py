"""Append-only event log behavior through the real server."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

from helpers import ask, open_authenticated, running_backend, stream_handler, stub_llm

FIXED_NOW = datetime(2025, 3, 4, 5, 6, 7, tzinfo=UTC)


async def _wait_for_lines(path: Path, count: int) -> None:
    for _ in range(200):
        if path.is_file() and len(path.read_text(encoding="utf-8").splitlines()) >= count:
            return
        await asyncio.sleep(0.01)
    raise AssertionError(f"event log did not reach {count} lines")


async def test_event_log_has_expected_events_and_is_append_only(tmp_path: Path) -> None:
    async with (
        stub_llm(stream_handler(["pong"])) as base_url,
        running_backend(tmp_path, base_url, clock=lambda: FIXED_NOW) as env,
    ):
        log_path = env.events_dir / "2025-03-04.jsonl"

        async with await open_authenticated(env.url, "desk", env.tokens["desk"]) as websocket:
            assert await ask(websocket, "t1", "ping") == "pong"
        await _wait_for_lines(log_path, 4)
        first_run = log_path.read_bytes()

        async with await open_authenticated(env.url, "desk", env.tokens["desk"]) as websocket:
            assert await ask(websocket, "t2", "ping again") == "pong"
        await _wait_for_lines(log_path, 8)
        second_run = log_path.read_bytes()

    assert second_run.startswith(first_run)
    assert len(second_run) > len(first_run)
    assert env.tokens["desk"] not in second_run.decode("utf-8")

    records = [json.loads(line) for line in second_run.decode("utf-8").splitlines()]
    assert [record["event"] for record in records] == [
        "connected",
        "user_text",
        "reply",
        "disconnected",
        "connected",
        "user_text",
        "reply",
        "disconnected",
    ]
    for record in records:
        assert record["ts"].startswith("2025-03-04T05:06:07")
        assert record["device_id"] == "desk"
    asked = [record for record in records if record["event"] == "user_text"]
    replies = [record for record in records if record["event"] == "reply"]
    assert [record["turn_id"] for record in asked] == ["t1", "t2"]
    assert [record["text"] for record in replies] == ["pong", "pong"]
