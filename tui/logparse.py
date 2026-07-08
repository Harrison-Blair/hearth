"""Parse the daemon's formatted log lines for routing into the TUI's views.

The daemon logs with ``"%(asctime)s %(levelname)-7s %(name)s: %(message)s"``
(see assistant/core/logging.py), datefmt ``%H:%M:%S``. Lines that don't match
(multi-line tracebacks, raw prints) are kept verbatim with empty fields.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

# "12:34:56 INFO    assistant.llm.ollama_provider: LLM response: hi"
_LINE = re.compile(r"^(\d{2}:\d{2}:\d{2})\s+([A-Z]+)\s+([\w.]+):\s(.*)$")

# Logger prefix whose lines also surface in the dedicated LLM view.
_LLM_PREFIX = "assistant.llm"

# Sentinel prefix for the daemon's state feed (assistant/core/state.py). We parse
# it inline rather than importing the daemon module — the tui may only depend on
# assistant.core.config and assistant.wake.registry (see CLAUDE.md).
_STATE_MARKER = "@@STATE "


@dataclass
class LogLine:
    timestamp: str | None
    level: str | None
    logger: str | None
    message: str
    raw: str

    @property
    def is_llm(self) -> bool:
        return bool(self.logger and self.logger.startswith(_LLM_PREFIX))


def parse(line: str) -> LogLine:
    line = line.rstrip("\n")
    m = _LINE.match(line)
    if not m:
        # Tracebacks, child print() output, blank lines: keep them in the app log.
        return LogLine(None, None, None, line, line)
    ts, level, logger, message = m.groups()
    return LogLine(ts, level, logger, message, line)


def parse_state(line: str) -> dict | None:
    """A ``@@STATE {json}`` feed line as its payload dict, else None (a log line)."""
    line = line.rstrip("\n")
    if not line.startswith(_STATE_MARKER):
        return None
    try:
        payload = json.loads(line[len(_STATE_MARKER):])
    except ValueError:
        return None
    return payload if isinstance(payload, dict) else None


def dedup_key(line: LogLine) -> str:
    """Key for collapsing consecutive duplicate log lines (ignores the timestamp).

    Two events that differ only by their per-second timestamp share a key, so a
    repeating message collapses. Unparsed lines (tracebacks, raw prints) fall back
    to the verbatim text — they collapse only when byte-identical."""
    if line.level is None:
        return line.raw
    return f"{line.level}\x00{line.logger}\x00{line.message}"
