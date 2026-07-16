"""Root logging setup: a `RotatingFileHandler` routing hearth's own logging
and the `websockets` library's logger to file, configured once at daemon
start from `LoggingConfig`.

Deliberately a plain function, never called at import time -- no
`logging.basicConfig` anywhere in this module -- so importing `hearth.*` in
tests has no logging side effect. `setup_logging` is idempotent: a marker
attribute on the root logger guards against stacking duplicate handlers
across repeated calls (e.g. across tests, or if `app.py` were ever called
twice).
"""
from __future__ import annotations

import logging
import logging.handlers
import os
import sys
from typing import Callable

from hearth.config import LoggingConfig

_CONFIGURED_MARKER = "_hearth_logging_configured"

# --- console color formatter (FTHR-016) -----------------------------------
#
# Console-only styling: a ` │ ` field delimiter, timestamp+level ANSI color
# keyed by level (ERROR/CRITICAL's color is reserved -- no other level, and
# no category rule below, may reuse it), a category-dispatch registry read
# off `record.category` (later feathers register entries here as they tag
# real call sites -- FTHR-017/018/019), and TTY/NO_COLOR auto-suppression.
# The rotating file handler keeps its own plain `logging.Formatter` above,
# untouched.

_DELIMITER = " │ "
_RESET = "\x1b[0m"

_LEVEL_COLORS = {
    logging.DEBUG: "\x1b[2m",  # dim
    logging.INFO: "",  # no color
    logging.WARNING: "\x1b[33m",  # yellow
    logging.ERROR: "\x1b[1;31m",  # bold red -- reserved, exclusive to ERROR/CRITICAL
    logging.CRITICAL: "\x1b[1;31m",
}

# Category name -> function coloring the message field. Empty until a later
# feather registers a real category (e.g. "metrics"); an unregistered or
# absent category (default "plain") falls back to level-only coloring.
_CATEGORY_COLORS: dict[str, Callable[[str], str]] = {}

# FTHR-018: connection-lifecycle lines (connect/disconnect/malformed-frame,
# `hearth/veneer/server.py`) -- cyan, distinct from the reserved error color.
_CATEGORY_COLORS["connection"] = lambda message: f"\x1b[36m{message}\x1b[0m"

# FTHR-019: daemon lifecycle lines (app.py::_run_daemon) -- cyan, distinct
# from the reserved ERROR/CRITICAL bold red.
_CATEGORY_COLORS["server"] = lambda message: f"\x1b[36m{message}{_RESET}"


class ColorFormatter(logging.Formatter):
    """Console-only formatter: fields joined by ` │ `, timestamp+level
    colored by `record.levelno`, and an optional per-category coloring rule
    applied to the message when `record.category` is registered. Colors are
    suppressed entirely (delimiter/content unaffected) when `sys.stdout` is
    not a TTY or `NO_COLOR` is set to a non-empty value.
    """

    def format(self, record: logging.LogRecord) -> str:
        use_color = sys.stdout.isatty() and not os.environ.get("NO_COLOR")

        timestamp = self.formatTime(record, self.datefmt)
        ts_level = _DELIMITER.join([timestamp, record.levelname])
        level_color = _LEVEL_COLORS.get(record.levelno, "") if use_color else ""
        if level_color:
            ts_level = f"{level_color}{ts_level}{_RESET}"

        message = record.getMessage()
        category = getattr(record, "category", "plain")
        colorize = _CATEGORY_COLORS.get(category) if use_color else None
        if colorize is not None:
            message = colorize(message)

        return _DELIMITER.join([ts_level, message])


def setup_logging(config: LoggingConfig) -> None:
    root = logging.getLogger()
    if getattr(root, _CONFIGURED_MARKER, False):
        return

    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")

    os.makedirs(config.dir, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(
        os.path.join(config.dir, config.file_name),
        maxBytes=config.max_bytes,
        backupCount=config.backup_count,
    )
    handler.setFormatter(formatter)
    handler.setLevel(config.level)

    # Every log line is written to the file; the same records are mirrored to
    # these handlers so the set can be attached identically to root and the
    # `websockets` logger below.
    handlers: list[logging.Handler] = [handler]

    # A stdout stream handler so running `hearth run` shows logs live in the
    # terminal as the daemon works -- useful while testing. Off via
    # `logging.console: false` for a quiet daemon (file logging is unaffected).
    if config.console:
        console = logging.StreamHandler(sys.stdout)
        console.setFormatter(ColorFormatter())
        console.setLevel(config.level)
        handlers.append(console)

    for h in handlers:
        root.addHandler(h)
    root.setLevel(config.level)
    setattr(root, _CONFIGURED_MARKER, True)

    # The `websockets` library logs its own keepalive/connection-close
    # messages; attach explicitly so those land in the file (and console) too
    # instead of falling through to Python's unconfigured-root stderr dump.
    ws_logger = logging.getLogger("websockets")
    for h in handlers:
        ws_logger.addHandler(h)
    ws_logger.setLevel(config.level)
    # Its own handlers already emit these records; without this, records also
    # propagate to the root handlers and every line is logged twice.
    ws_logger.propagate = False
