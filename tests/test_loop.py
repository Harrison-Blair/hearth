"""Loop.run_turn: single-completion, history-aware, logged turn. Hermetic via MockTransport."""
from __future__ import annotations

import json
import logging

import httpx
import pytest

from hearth.brain.errors import BrainError
from hearth.brain.router import Router
from hearth.loop import Loop
from hearth.memory.log import EventLog


PERSONA_PROMPT = "You are Calcifer."


class _Conversation:
    def __init__(self, max_history_turns: int) -> None:
        self.max_history_turns = max_history_turns


class _Agent:
    def __init__(self, max_consult_rounds: int = 3, turn_timeout_s: float = 45.0) -> None:
        self.max_consult_rounds = max_consult_rounds
        self.turn_timeout_s = turn_timeout_s


class _Persona:
    def __init__(self, system_prompt: str = PERSONA_PROMPT) -> None:
        self.system_prompt = system_prompt


class _Config:
    def __init__(self, max_history_turns: int = 12) -> None:
        self.conversation = _Conversation(max_history_turns)
        self.agent = _Agent()
        self.persona = _Persona()


def _make_router(handler, llm_config):
    backend_config = llm_config.backends["local"]
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url=backend_config.base_url
    )
    return Router(llm_config, clients={"local": client}), client


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

    # Second turn's request carries the persona system prompt as messages[0]
    # (FTHR-009), then the first exchange.
    second_contents = [m["content"] for m in requests_seen[1]["messages"]]
    assert second_contents == [PERSONA_PROMPT, "first message", "answer 1", "second message"]

    # Third turn's request drops the first exchange (bounded by max_history_turns=1)
    # but retains the second.
    third_contents = [m["content"] for m in requests_seen[2]["messages"]]
    assert "first message" not in third_contents
    assert third_contents == [PERSONA_PROMPT, "second message", "answer 2", "third message"]

    await client.aclose()


async def test_loop_logs_per_call_and_per_turn_metrics(
    tmp_path, llm_config, canned_completion, caplog
):
    """AC-3/AC-4: a per-call INFO line (tier/round/in/out/thinking) and a
    per-turn summary INFO line (turn number + aggregate totals) are emitted;
    the turn number increments across turns in the same session."""
    caplog.set_level(logging.INFO)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=canned_completion(
                text="answer one",
                usage={"prompt_tokens": 12, "completion_tokens": 6, "total_tokens": 18},
            ),
        )

    router, client = _make_router(handler, llm_config)
    log = EventLog(str(tmp_path / "events.db"))
    loop = Loop(router, log, _Config())

    await loop.run_turn("s1", "t1", "hello")

    messages = [record.getMessage() for record in caplog.records]

    call_lines = [m for m in messages if "round=1" in m and "tier=" in m]
    assert call_lines, messages
    assert "in=" in call_lines[0]
    assert "out=" in call_lines[0]
    assert "thinking=n/a" in call_lines[0]

    summary_lines = [m for m in messages if "turn=1" in m]
    assert summary_lines, messages

    caplog.clear()
    await loop.run_turn("s1", "t2", "hello again")
    messages = [record.getMessage() for record in caplog.records]
    assert any("turn=2" in m for m in messages), messages

    await client.aclose()


async def test_loop_logs_failed_marker_on_brain_error_never_leaks_detail(
    tmp_path, llm_config, caplog
):
    """AC-2: a `BrainError` from `brain.complete()` produces a one-line
    FAILED marker at WARNING level (tier, round, `.reason`) before
    propagating unchanged, and `.detail` (which may carry raw HTTP body
    text) never appears in the log output."""
    caplog.set_level(logging.WARNING)

    secret_body = "internal-diagnostic-body-should-never-be-logged"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text=secret_body)

    router, client = _make_router(handler, llm_config)
    log = EventLog(str(tmp_path / "events.db"))
    loop = Loop(router, log, _Config())

    with pytest.raises(BrainError) as excinfo:
        await loop.run_turn("s1", "t1", "hello")

    assert secret_body in excinfo.value.detail  # sanity: detail really carries it

    messages = [record.getMessage() for record in caplog.records]
    failed_lines = [m for m in messages if "FAILED" in m]
    assert failed_lines, messages
    assert "tier=" in failed_lines[0]
    assert "round=1" in failed_lines[0]
    assert "backend error" in failed_lines[0]  # BrainError.reason for a status error

    full_log = "\n".join(messages)
    assert secret_body not in full_log

    await client.aclose()


async def test_metrics_calls_carry_category_tag(
    tmp_path, llm_config, canned_completion, caplog
):
    """FTHR-017 AC-2: the per-call and per-turn metrics INFO lines carry
    `category="metrics"` (no change to message text or level) so the console
    formatter can style them."""
    caplog.set_level(logging.INFO)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=canned_completion(
                text="answer one",
                usage={"prompt_tokens": 12, "completion_tokens": 6, "total_tokens": 18},
            ),
        )

    router, client = _make_router(handler, llm_config)
    log = EventLog(str(tmp_path / "events.db"))
    loop = Loop(router, log, _Config())

    await loop.run_turn("s1", "t1", "hello")

    call_records = [
        r for r in caplog.records if "round=1" in r.getMessage() and "tier=" in r.getMessage()
    ]
    assert call_records
    assert call_records[0].category == "metrics"

    summary_records = [r for r in caplog.records if "turn=1" in r.getMessage()]
    assert summary_records
    assert summary_records[0].category == "metrics"

    await client.aclose()


async def test_failed_marker_carries_category_tag(tmp_path, llm_config, caplog):
    """FTHR-017 AC-2: the FAILED-call WARNING marker also carries
    `category="metrics"` (no change to message text or level)."""
    caplog.set_level(logging.WARNING)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    router, client = _make_router(handler, llm_config)
    log = EventLog(str(tmp_path / "events.db"))
    loop = Loop(router, log, _Config())

    with pytest.raises(BrainError):
        await loop.run_turn("s1", "t1", "hello")

    failed_records = [r for r in caplog.records if "FAILED" in r.getMessage()]
    assert failed_records
    assert failed_records[0].category == "metrics"

    await client.aclose()


async def test_persona_restyle_noop():
    from hearth.persona import restyle

    assert await restyle("verbatim text", ctx=None) == "verbatim text"
