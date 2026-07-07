"""Restart-in-place primitive (source run mode).

Re-execs the current interpreter as ``python -m assistant.app``, replacing the
process image so a fresh interpreter loads whatever code is currently on disk.
No network, no git, no subprocess — updating the on-disk code (if any) already
happened before this is called; this only reloads it.
"""

from __future__ import annotations

import logging
import os
import sys

log = logging.getLogger(__name__)


def restart_in_place() -> None:
    """Flush stdio, log, then replace this process with a fresh daemon."""
    log.info("Restarting in place to load updated code...")
    sys.stdout.flush()
    sys.stderr.flush()
    os.execv(sys.executable, [sys.executable, "-m", "assistant.app"])
