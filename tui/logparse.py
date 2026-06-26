"""Parse the daemon's formatted log lines for routing into the TUI's views.

The daemon logs with ``"%(asctime)s %(levelname)-7s %(name)s: %(message)s"``
(see assistant/core/logging.py), datefmt ``%H:%M:%S``. Lines that don't match
(multi-line tracebacks, raw prints) are kept verbatim with empty fields.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# "12:34:56 INFO    assistant.llm.ollama_provider: LLM response: hi"
_LINE = re.compile(r"^(\d{2}:\d{2}:\d{2})\s+([A-Z]+)\s+([\w.]+):\s(.*)$")

# Logger prefix whose lines also surface in the dedicated LLM view.
_LLM_PREFIX = "assistant.llm"


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


def dedup_key(line: LogLine) -> str:
    """Key for collapsing consecutive duplicate log lines (ignores the timestamp).

    Two events that differ only by their per-second timestamp share a key, so a
    repeating message collapses. Unparsed lines (tracebacks, raw prints) fall back
    to the verbatim text — they collapse only when byte-identical."""
    if line.level is None:
        return line.raw
    return f"{line.level}\x00{line.logger}\x00{line.message}"
