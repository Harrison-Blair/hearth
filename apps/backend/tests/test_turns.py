"""End-to-end backend turns over a real WebSocket and stub LLM."""

from __future__ import annotations

from pathlib import Path

from helpers import (
    ask,
    open_authenticated,
    running_backend,
    stream_handler,
    stub_llm,
)

from hearth.protocol import (
    ReplyDeltaMessage,
    ReplyDoneMessage,
    UserTextMessage,
    parse_server_message,
    serialize,
)


async def test_streams_known_reply_then_done_with_same_turn_id(tmp_path: Path) -> None:
    async with (
        stub_llm(stream_handler(["Hello ", "world"])) as base_url,
        running_backend(tmp_path, base_url) as env,
        await open_authenticated(env.url, "desk", env.tokens["desk"]) as websocket,
    ):
        await websocket.send(serialize(UserTextMessage(turn_id="turn-1", text="hi")))
        pieces: list[str] = []
        done: ReplyDoneMessage | None = None
        while done is None:
            parsed = parse_server_message(await websocket.recv())
            if isinstance(parsed, ReplyDeltaMessage):
                pieces.append(parsed.text)
            elif isinstance(parsed, ReplyDoneMessage):
                done = parsed
            else:
                raise AssertionError(f"unexpected frame: {parsed}")

    assert "".join(pieces) == "Hello world"
    assert done.turn_id == "turn-1"


async def test_second_turn_gets_first_turn_from_other_device_in_prompt(
    tmp_path: Path,
) -> None:
    requests: list[dict[str, object]] = []
    async with (
        stub_llm(stream_handler(["noted"], requests=requests)) as base_url,
        running_backend(tmp_path, base_url, device_ids=("A", "B")) as env,
    ):
        async with await open_authenticated(env.url, "A", env.tokens["A"]) as websocket_a:
            assert await ask(websocket_a, "a-1", "kitchen lights on") == "noted"

        async with await open_authenticated(env.url, "B", env.tokens["B"]) as websocket_b:
            assert await ask(websocket_b, "b-1", "what did A say?") == "noted"

    assert len(requests) == 2
    second_messages = requests[1]["messages"]
    assert isinstance(second_messages, list)
    assert second_messages == [
        {"role": "user", "content": "[A] kitchen lights on"},
        {"role": "assistant", "content": "noted"},
        {"role": "user", "content": "[B] what did A say?"},
    ]
