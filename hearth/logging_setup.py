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

from hearth.config import LoggingConfig

_CONFIGURED_MARKER = "_hearth_logging_configured"


def setup_logging(config: LoggingConfig) -> None:
    root = logging.getLogger()
    if getattr(root, _CONFIGURED_MARKER, False):
        return

    os.makedirs(config.dir, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(
        os.path.join(config.dir, config.file_name),
        maxBytes=config.max_bytes,
        backupCount=config.backup_count,
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    handler.setLevel(config.level)

    root.addHandler(handler)
    root.setLevel(config.level)
    setattr(root, _CONFIGURED_MARKER, True)

    # The `websockets` library logs its own keepalive/connection-close
    # messages; attach explicitly so those land in the file too instead of
    # falling through to Python's unconfigured-root stderr dump.
    ws_logger = logging.getLogger("websockets")
    ws_logger.addHandler(handler)
    ws_logger.setLevel(config.level)
