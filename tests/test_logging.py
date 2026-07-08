"""Tests for the logging service: JSONL formatter, per-run files, pruning."""

from __future__ import annotations

import json
import logging
import re
import sys
from pathlib import Path

import pytest

from assistant.core.logging import (
    CONSOLE_DATEFMT,
    CONSOLE_FORMAT,
    JsonlFormatter,
    prune_runs,
    run_id,
    setup_logging,
)


def _record(msg: str = "hello %s", args: tuple = ("world",), **extra) -> logging.LogRecord:
    record = logging.LogRecord(
        name="assistant.test", level=logging.INFO, pathname=__file__, lineno=1,
        msg=msg, args=args, exc_info=extra.pop("exc_info", None),
    )
    for key, value in extra.items():
        setattr(record, key, value)
    return record


@pytest.fixture
def restore_root():
    root = logging.getLogger()
    saved_handlers = root.handlers[:]
    saved_level = root.level
    yield
    root.handlers[:] = saved_handlers
    root.setLevel(saved_level)


# ---- JsonlFormatter ----------------------------------------------------------


def test_jsonl_formatter_basic():
    entry = json.loads(JsonlFormatter().format(_record()))
    assert entry["level"] == "INFO"
    assert entry["logger"] == "assistant.test"
    assert entry["message"] == "hello world"
    assert re.match(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}", entry["ts"])


def test_jsonl_formatter_includes_extra_data():
    entry = json.loads(JsonlFormatter().format(_record(data={"kind": "llm.chat", "n": 2})))
    assert entry["data"] == {"kind": "llm.chat", "n": 2}
    assert "data" not in json.loads(JsonlFormatter().format(_record()))


def test_jsonl_formatter_exception_and_unserializable():
    try:
        raise ValueError("boom")
    except ValueError:
        exc_info = sys.exc_info()
    entry = json.loads(
        JsonlFormatter().format(_record(exc_info=exc_info, data={"path": Path("/tmp/x")}))
    )
    assert "ValueError: boom" in entry["exc"]
    assert entry["data"]["path"] == "/tmp/x"  # default=str fallback


# ---- run naming / pruning ----------------------------------------------------


def test_run_id_format():
    assert re.fullmatch(r"\d{8}-\d{6}", run_id())


def test_prune_runs(tmp_path):
    stamps = ["20260101-000001", "20260101-000002", "20260101-000003", "20260101-000004"]
    for stamp in stamps:
        run_dir = tmp_path / f"assistant-{stamp}"
        run_dir.mkdir()
        (run_dir / "assistant.log").touch()
        (run_dir / "assistant.jsonl").touch()
        (run_dir / "assistant.log.1").touch()
    (tmp_path / f"ollama-{stamps[0]}").mkdir()
    (tmp_path / "unrelated.log").touch()

    deleted = prune_runs(tmp_path, keep=2)

    remaining = {p.name for p in tmp_path.iterdir()}
    for stamp in stamps[2:]:  # newest two runs kept, contents intact
        assert f"assistant-{stamp}" in remaining
        assert (tmp_path / f"assistant-{stamp}" / "assistant.log.1").exists()
    for stamp in stamps[:2]:
        assert f"assistant-{stamp}" not in remaining
    # The ollama family is pruned independently: its only run survives keep=2.
    assert f"ollama-{stamps[0]}" in remaining
    assert "unrelated.log" in remaining
    assert len(deleted) == 2


def test_prune_runs_keep_zero_keeps_all(tmp_path):
    (tmp_path / "assistant-20260101-000001").mkdir()
    assert prune_runs(tmp_path, keep=0) == []
    assert (tmp_path / "assistant-20260101-000001").is_dir()


# ---- setup_logging -----------------------------------------------------------


def test_setup_logging_writes_both_files(tmp_path, restore_root):
    setup_logging("INFO", log_dir=str(tmp_path), run="20260101-120000")
    payload = {"kind": "llm.complete", "prompt": "p" * 500, "latency_ms": 42}
    logging.getLogger("assistant.test").info("short line", extra={"data": payload})
    for handler in logging.getLogger().handlers:
        handler.flush()

    run_dir = tmp_path / "assistant-20260101-120000"
    plain = (run_dir / "assistant.log").read_text()
    assert re.search(r"\d{2}:\d{2}:\d{2} INFO    assistant\.test: short line", plain)
    lines = (run_dir / "assistant.jsonl").read_text().splitlines()
    entries = [json.loads(line) for line in lines]
    traced = [e for e in entries if e.get("data")]
    assert traced[0]["message"] == "short line"
    assert traced[0]["data"] == payload


def test_setup_logging_console_only(restore_root):
    setup_logging("INFO", log_dir=None)
    handlers = logging.getLogger().handlers
    assert len(handlers) == 1
    assert isinstance(handlers[0], logging.StreamHandler)
    assert handlers[0].formatter._fmt == CONSOLE_FORMAT
    assert handlers[0].formatter.datefmt == CONSOLE_DATEFMT


def test_setup_logging_idempotent(tmp_path, restore_root):
    setup_logging("INFO", log_dir=str(tmp_path), run="20260101-120000")
    setup_logging("INFO", log_dir=str(tmp_path), run="20260101-120000")
    assert len(logging.getLogger().handlers) == 3  # console + plain + jsonl, not doubled
