"""Append a supervised child's output lines to a per-run log file."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import IO


class RunLogWriter:
    """Line-oriented append writer with a single size-based rotation (`<path>.1`)."""

    def __init__(self, path: Path, max_bytes: int = 10_485_760) -> None:
        self._path = path
        self._max_bytes = max_bytes
        self._file: IO[str] | None = None

    def write(self, line: str) -> None:
        if self._file is None:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._file = self._path.open("a", encoding="utf-8")
        self._file.write(line + "\n")
        self._file.flush()
        if self._file.tell() > self._max_bytes:
            self._file.close()
            self._path.replace(self._path.with_name(self._path.name + ".1"))
            self._file = self._path.open("a", encoding="utf-8")

    def close(self) -> None:
        if self._file is not None:
            self._file.close()
            self._file = None


def ollama_log_path(log_dir: str) -> Path:
    """Per-run file for the spawned Ollama server's output, stamped at call time."""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return Path(log_dir) / f"ollama-{stamp}" / "ollama.log"
