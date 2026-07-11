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

from hearth.config import LoggingConfig

_CONFIGURED_MARKER = "_hearth_logging_configured"


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
        console.setFormatter(formatter)
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
