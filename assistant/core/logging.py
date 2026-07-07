"""Logging setup: console (TUI-parsed format) plus per-run plain-text and JSONL files."""

from __future__ import annotations

import json
import logging
import re
import shutil
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

log = logging.getLogger(__name__)

# The TUI parses console lines with a regex keyed to this exact format
# (tui/logparse.py) — do not change it without updating the parser in lockstep.
CONSOLE_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
CONSOLE_DATEFMT = "%H:%M:%S"

# Per-run directories: <family>-<YYYYmmdd-HHMMSS>/ holding that run's files. The
# daemon writes assistant-*/ (plain + JSONL); the TUI writes ollama-*/ (its
# spawned server's output).
_RUN_DIR = re.compile(r"^(assistant|ollama)-(\d{8}-\d{6})$")


class JsonlFormatter(logging.Formatter):
    """One JSON object per record, including the reserved ``extra={"data": {...}}`` dict."""

    def format(self, record: logging.LogRecord) -> str:
        entry: dict = {
            "ts": datetime.fromtimestamp(record.created)
            .astimezone()
            .isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        data = getattr(record, "data", None)
        if data is not None:
            entry["data"] = data
        if record.exc_info:
            entry["exc"] = self.formatException(record.exc_info)
        # default=str: an unserializable payload degrades to its repr, never crashes.
        return json.dumps(entry, ensure_ascii=False, default=str)


def run_id(now: datetime | None = None) -> str:
    """Timestamp naming one run's log files, e.g. ``20260706-153000``."""
    return (now or datetime.now()).strftime("%Y%m%d-%H%M%S")


def prune_runs(log_dir: str | Path, keep: int) -> list[Path]:
    """Delete the run directories of all but the newest ``keep`` runs per family
    (0 or less keeps all). Returns the deleted directories."""
    if keep <= 0:
        return []
    directory = Path(log_dir)
    if not directory.is_dir():
        return []
    runs: dict[str, list[tuple[str, Path]]] = {}
    for path in directory.iterdir():
        match = _RUN_DIR.match(path.name)
        if not path.is_dir() or match is None:
            continue
        runs.setdefault(match.group(1), []).append((match.group(2), path))
    deleted: list[Path] = []
    for family_runs in runs.values():
        family_runs.sort(reverse=True)  # stamps sort lexicographically = newest first
        for _, path in family_runs[keep:]:
            shutil.rmtree(path, ignore_errors=True)
            deleted.append(path)
    return deleted


def setup_logging(
    level: str = "INFO",
    *,
    log_dir: str | None = None,
    file_level: str = "INFO",
    rotate_max_bytes: int = 10_485_760,
    rotate_backups: int = 3,
    runs_to_keep: int = 20,
    run: str | None = None,
) -> None:
    """Install the console handler, and per-run file handlers when ``log_dir`` is set."""
    console_level = getattr(logging, level.upper(), logging.INFO)
    console = logging.StreamHandler()
    console.setLevel(console_level)
    console.setFormatter(logging.Formatter(CONSOLE_FORMAT, datefmt=CONSOLE_DATEFMT))
    handlers: list[logging.Handler] = [console]

    plain_path: Path | None = None
    if log_dir:
        directory = Path(log_dir)
        directory.mkdir(parents=True, exist_ok=True)
        prune_runs(directory, runs_to_keep)
        run_dir = directory / f"assistant-{run or run_id()}"
        run_dir.mkdir(parents=True, exist_ok=True)
        handler_level = getattr(logging, file_level.upper(), logging.INFO)
        plain_path = run_dir / "assistant.log"
        plain = RotatingFileHandler(
            plain_path, maxBytes=rotate_max_bytes, backupCount=rotate_backups, encoding="utf-8"
        )
        plain.setFormatter(logging.Formatter(CONSOLE_FORMAT, datefmt=CONSOLE_DATEFMT))
        jsonl = RotatingFileHandler(
            run_dir / "assistant.jsonl",
            maxBytes=rotate_max_bytes,
            backupCount=rotate_backups,
            encoding="utf-8",
        )
        jsonl.setFormatter(JsonlFormatter())
        for handler in (plain, jsonl):
            handler.setLevel(handler_level)
            handlers.append(handler)

    root = logging.getLogger()
    root.handlers[:] = handlers
    root.setLevel(min(h.level for h in handlers))
    if plain_path is not None:
        log.info("Logging to %s", plain_path)
