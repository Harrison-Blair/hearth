"""Tests for the TUI's per-run child-output log writer."""

from __future__ import annotations

import re

from tui.runlog import RunLogWriter, ollama_log_path


def test_write_appends_lines(tmp_path):
    writer = RunLogWriter(tmp_path / "ollama-x.log")
    writer.write("first")
    writer.write("second")
    writer.close()
    assert (tmp_path / "ollama-x.log").read_text() == "first\nsecond\n"


def test_write_creates_parent_dir(tmp_path):
    writer = RunLogWriter(tmp_path / "logs" / "ollama-x.log")
    writer.write("line")
    writer.close()
    assert (tmp_path / "logs" / "ollama-x.log").read_text() == "line\n"


def test_rotation_past_max_bytes(tmp_path):
    path = tmp_path / "ollama-x.log"
    writer = RunLogWriter(path, max_bytes=20)
    writer.write("a" * 25)  # exceeds the cap -> rotated out
    writer.write("fresh")
    writer.close()
    assert (tmp_path / "ollama-x.log.1").read_text() == "a" * 25 + "\n"
    assert path.read_text() == "fresh\n"


def test_close_is_safe_twice_and_before_write(tmp_path):
    writer = RunLogWriter(tmp_path / "ollama-x.log")
    writer.close()
    writer.close()
    assert not (tmp_path / "ollama-x.log").exists()  # lazy open: no file until a write


def test_ollama_log_path_shape(tmp_path):
    path = ollama_log_path(str(tmp_path))
    assert path.name == "ollama.log"
    assert re.fullmatch(r"ollama-\d{8}-\d{6}", path.parent.name)
    assert path.parent.parent == tmp_path
