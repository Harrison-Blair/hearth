"""Loop.run_turn: single-completion, history-aware, logged turn. Hermetic via MockTransport."""
from __future__ import annotations

import json

import httpx

from hearth.brain.router import Router
from hearth.loop import Loop
from hearth.memory.log import EventLog


class _Conversation:
    def __init__(self, max_history_turns: int) -> None:
        self.max_history_turns = max_history_turns


class _Config:
    def __init__(self, max_history_turns: int = 12) -> None:
        self.conversation = _Conversation(max_history_turns)


def _make_router(handler, llm_config):
    backend_config = llm_config.backends["local"]
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url=backend_config.base_url
    )
    return Router(llm_config, client=client), client


async def test_loop_single_turn_logs_and_answers(tmp_path, llm_config, canned_completion):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=canned_completion(text="answer one"))

    router, client = _make_router(handler, llm_config)
    log = EventLog(str(tmp_path / "events.db"))
    loop = Loop(router, log, _Config())

    answer = await loop.run_turn("s1", "t1", "hello")

    assert answer == "answer one"
    events = log.read_session("s1")
    assert [e.type for e in events] == ["user_input", "routing_decision", "final_answer"]
    assert events[0].payload == {"text": "hello"}
    assert events[1].payload["backend_name"] == "local"
    assert events[1].payload["tier"] == "default"
    assert events[2].payload == {"text": "answer one"}

    await client.aclose()


async def test_loop_multi_turn_reconstructs_history(tmp_path, llm_config, canned_completion):
    requests_seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requests_seen.append(body)
        text = f"answer {len(requests_seen)}"
        return httpx.Response(200, json=canned_completion(text=text))

    # max_history_turns=1: only the immediately prior exchange is retained.
    router, client = _make_router(handler, llm_config)
    log = EventLog(str(tmp_path / "events.db"))
    loop = Loop(router, log, _Config(max_history_turns=1))

    await loop.run_turn("s1", "t1", "first message")
    await loop.run_turn("s1", "t2", "second message")
    await loop.run_turn("s1", "t3", "third message")

    # Second turn's request includes the first exchange.
    second_contents = [m["content"] for m in requests_seen[1]["messages"]]
    assert second_contents == ["first message", "answer 1", "second message"]

    # Third turn's request drops the first exchange (bounded by max_history_turns=1)
    # but retains the second.
    third_contents = [m["content"] for m in requests_seen[2]["messages"]]
    assert "first message" not in third_contents
    assert third_contents == ["second message", "answer 2", "third message"]

    await client.aclose()


async def test_persona_restyle_noop():
    from hearth.persona import restyle

    assert await restyle("verbatim text", ctx=None) == "verbatim text"
