"""Logging infra + dual-model logging + per-session transcript (FTHR-011).

Covers: a rotating file handler configured once from `LoggingConfig` and
routed for both hearth's own loggers and `websockets`; a consult-driving turn
logging both the local orchestrator model and the remote consult model; a
per-session transcript file with ordered turn lines; and that a forced
logging/transcript write failure never crashes a turn (AC-5).
"""
from __future__ import annotations

import json
import logging

import httpx

from hearth.brain.router import Router
from hearth.config import AgentConfig, LoggingConfig, PersonaConfig
from hearth.memory.log import EventLog


def test_setup_logging_creates_rotating_handler(tmp_path):
    from logging.handlers import RotatingFileHandler

    from hearth.logging_setup import setup_logging

    config = LoggingConfig(
        dir=str(tmp_path), file_name="hearth.log", max_bytes=12345, backup_count=2
    )
    setup_logging(config)

    root = logging.getLogger()
    rotating = [h for h in root.handlers if isinstance(h, RotatingFileHandler)]
    assert len(rotating) == 1
    assert rotating[0].maxBytes == 12345
    assert rotating[0].backupCount == 2

    logging.getLogger("some.module").info("hello from the log")

    log_path = tmp_path / "hearth.log"
    assert log_path.exists()
    assert "hello from the log" in log_path.read_text()


def test_setup_logging_is_idempotent(tmp_path):
    from logging.handlers import RotatingFileHandler

    from hearth.logging_setup import setup_logging

    config = LoggingConfig(dir=str(tmp_path), file_name="hearth.log")
    setup_logging(config)
    setup_logging(config)

    root = logging.getLogger()
    rotating = [h for h in root.handlers if isinstance(h, RotatingFileHandler)]
    assert len(rotating) == 1


def test_websockets_logger_routed_to_file(tmp_path):
    from hearth.logging_setup import setup_logging

    config = LoggingConfig(dir=str(tmp_path), file_name="hearth.log")
    setup_logging(config)

    logging.getLogger("websockets").warning("keepalive ping timed out")

    log_path = tmp_path / "hearth.log"
    assert log_path.exists()
    assert "keepalive ping timed out" in log_path.read_text()


# --- dual-model logging + transcript: drive a full consult-triggering turn ---


class _WikiSpec:
    from hearth.brain.base import ToolSpec

    SPEC = ToolSpec(
        name="wikipedia_search",
        description="Search Wikipedia.",
        parameters={
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
        label="search",
    )


class _FakeRegistry:
    def specs(self):
        return [_WikiSpec.SPEC]

    async def dispatch(self, name: str, args: dict) -> str:
        return "Ada Lovelace: a mathematician."


class _Conversation:
    max_history_turns = 12


class _Config:
    """Minimal settings-like object -- both `Loop` and `BrainConsult` only
    reach `.llm`, `.agent`, `.persona`, `.conversation` off their injected
    config."""

    def __init__(self, llm_config):
        self.llm = llm_config
        self.conversation = _Conversation()
        self.agent = AgentConfig(max_consult_rounds=3, max_tool_rounds=3, turn_timeout_s=45.0)
        self.persona = PersonaConfig(
            system_prompt="You are Calcifer.",
            brain_guard_prompt="Internal research subsystem; no persona.",
        )


def _tool_call_completion(name: str, arguments: dict, call_id: str = "call_1") -> dict:
    return {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": call_id,
                            "type": "function",
                            "function": {"name": name, "arguments": json.dumps(arguments)},
                        }
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ]
    }


def _chat_completion(text: str) -> dict:
    return {"choices": [{"message": {"role": "assistant", "content": text}, "finish_reason": "stop"}]}


def _drive_consult_turn(two_tier_llm_config, transcript=None):
    """Build a `Loop` + `BrainConsult` pair over MockTransports so a single
    `run_turn` call triggers exactly one nested `consult_brain` -> wikipedia
    round trip, and return (loop, log, clients)."""
    from hearth.loop import Loop
    from hearth.tools.consult import BrainConsult

    local_calls = []

    def local_handler(request: httpx.Request) -> httpx.Response:
        local_calls.append(json.loads(request.content))
        if len(local_calls) == 1:
            return httpx.Response(
                200,
                json=_tool_call_completion("consult_brain", {"query": "who was Ada Lovelace"}),
            )
        return httpx.Response(200, json=_chat_completion("Ada Lovelace was a mathematician."))

    remote_calls = []

    def remote_handler(request: httpx.Request) -> httpx.Response:
        remote_calls.append(json.loads(request.content))
        if len(remote_calls) == 1:
            return httpx.Response(
                200, json=_tool_call_completion("wikipedia_search", {"query": "Ada Lovelace"})
            )
        return httpx.Response(200, json=_chat_completion("Ada Lovelace: a 19th century mathematician."))

    local_backend = two_tier_llm_config.backends["local"]
    remote_backend = two_tier_llm_config.backends["remote"]
    local_client = httpx.AsyncClient(
        transport=httpx.MockTransport(local_handler), base_url=local_backend.base_url
    )
    remote_client = httpx.AsyncClient(
        transport=httpx.MockTransport(remote_handler), base_url=remote_backend.base_url
    )
    router = Router(two_tier_llm_config, clients={"local": local_client, "remote": remote_client})

    config = _Config(two_tier_llm_config)

    def make(log, extra_kwargs=None):
        extra_kwargs = extra_kwargs or {}
        registry = _FakeRegistry()
        consult = BrainConsult(router, registry, log, config, transcript=transcript)
        loop = Loop(router, log, config, consult=consult, transcript=transcript, **extra_kwargs)
        return loop

    return make, [local_client, remote_client]


async def test_consult_turn_logs_both_models(tmp_path, two_tier_llm_config, caplog):
    caplog.set_level(logging.INFO)

    make, clients = _drive_consult_turn(two_tier_llm_config)
    log = EventLog(str(tmp_path / "events.db"))
    loop = make(log)

    answer = await loop.run_turn("s1", "t1", "who was Ada Lovelace")

    assert answer == "Ada Lovelace was a mathematician."

    messages = [record.getMessage() for record in caplog.records]
    assert any("local" in m and "qwen3:14b" in m for m in messages)
    assert any("remote" in m and "openrouter/free" in m for m in messages)

    for client in clients:
        await client.aclose()


async def test_transcript_contains_ordered_turn_lines(tmp_path, two_tier_llm_config):
    from hearth.transcript import Transcript

    transcript_dir = tmp_path / "transcripts"
    transcript = Transcript(str(transcript_dir))

    make, clients = _drive_consult_turn(two_tier_llm_config, transcript=transcript)
    log = EventLog(str(tmp_path / "events.db"))
    loop = make(log)

    answer = await loop.run_turn("s1", "t1", "who was Ada Lovelace")

    contents = (transcript_dir / "s1.txt").read_text()
    user_pos = contents.index("who was Ada Lovelace")
    query_pos = contents.index("who was Ada Lovelace", user_pos + 1)
    findings_pos = contents.index("Ada Lovelace: a 19th century mathematician.")
    answer_pos = contents.index(answer)

    assert user_pos < query_pos < findings_pos < answer_pos

    for client in clients:
        await client.aclose()


async def test_logging_failure_does_not_crash_turn(tmp_path, llm_config, canned_completion, monkeypatch):
    import hearth.loop as loop_module
    from hearth.loop import Loop

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=canned_completion(text="answer one"))

    backend_config = llm_config.backends["local"]
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url=backend_config.base_url
    )
    router = Router(llm_config, clients={"local": client})
    log = EventLog(str(tmp_path / "events.db"))
    config = _Config(llm_config)

    class _RaisingTranscript:
        def append(self, session_id: str, line: str) -> None:
            raise RuntimeError("disk full")

    def _raise(*args, **kwargs):
        raise RuntimeError("logging broke")

    monkeypatch.setattr(loop_module.logger, "info", _raise)

    loop = Loop(router, log, config, transcript=_RaisingTranscript())

    answer = await loop.run_turn("s1", "t1", "hello")

    assert answer == "answer one"

    await client.aclose()
