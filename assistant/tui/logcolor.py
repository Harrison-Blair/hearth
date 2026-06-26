"""Colorize daemon/Ollama log lines into Rich ``Text`` for the TUI log views.

Reuses :func:`assistant.tui.logparse.parse` to split the daemon's
``"%(asctime)s %(levelname)-7s %(name)s: %(message)s"`` format, then styles each
field (high-contrast bold palette). Lines that aren't daemon-formatted — tracebacks,
the Ollama server's own GIN/slog output — get a best-effort pass that highlights
level keywords, HTTP status codes, and quoted content. Every function is total: it
never raises, and the returned ``Text.plain`` round-trips the input verbatim.
"""

from __future__ import annotations

import re

from rich.text import Text

from assistant.tui.logparse import parse

# High-contrast bold palette, keyed by Python log level.
LEVEL_STYLES: dict[str, str] = {
    "DEBUG": "grey50",
    "INFO": "bold bright_green",
    "WARNING": "bold bright_yellow",
    "ERROR": "bold white on red",
    "CRITICAL": "bold white on red",
}

_TIMESTAMP_STYLE = "bold bright_cyan"
_LOGGER_STYLE = "bold bright_blue"
_QUOTE_STYLE = "bold bright_green"
_TAG_STYLE = "bold bright_cyan"
_LABEL_STYLE = "bold"

# Single- or double-quoted spans, e.g. Reply: 'it is noon' or "foo".
_QUOTED = re.compile(r"'[^']*'|\"[^\"]*\"")
# Leading "[tag] label:" on LLM messages, e.g. "[classify] prompt: ...".
_LLM_TAG = re.compile(r"^(\[[^\]]+\])\s*(prompt:|system:|response:)?")
# Freeform level keywords (Ollama uses WARN; Python uses WARNING).
_FREEFORM_LEVEL = re.compile(r"\b(DEBUG|INFO|WARNING|WARN|ERROR|CRITICAL)\b")
# HTTP status codes.
_STATUS = re.compile(r"\b([1-5]\d\d)\b")


def colorize_line(line: str) -> Text:
    """Style a full log line for the Logs/Ollama views."""
    parsed = parse(line)
    if parsed.timestamp is None or parsed.level is None or parsed.logger is None:
        # Tracebacks, Ollama server lines, app notices: best-effort only.
        return _style_freeform(parsed.raw)

    text = Text()
    text.append(parsed.timestamp, style=_TIMESTAMP_STYLE)
    text.append(" ")
    # Preserve the formatter's left-padding (levelname is "%-7s").
    text.append(f"{parsed.level:<7}", style=LEVEL_STYLES.get(parsed.level, ""))
    text.append(" ")
    text.append(parsed.logger, style=_LOGGER_STYLE)
    text.append(": ")
    text.append(_style_message(parsed.message))
    return text


def colorize_message(message: str) -> Text:
    """Style just the message portion for the LLM view."""
    return _style_message(message)


def _style_message(message: str) -> Text:
    """Highlight a [tag], a prompt:/system:/response: label, and quoted content."""
    text = Text(message)
    m = _LLM_TAG.match(message)
    if m:
        text.stylize(_TAG_STYLE, m.start(1), m.end(1))
        if m.group(2):
            text.stylize(_LABEL_STYLE, m.start(2), m.end(2))
    for q in _QUOTED.finditer(message):
        text.stylize(_QUOTE_STYLE, q.start(), q.end())
    return text


def _style_freeform(line: str) -> Text:
    """Best-effort highlights for non-daemon lines (Ollama server output)."""
    text = Text(line)
    for m in _FREEFORM_LEVEL.finditer(line):
        key = "WARNING" if m.group(1) == "WARN" else m.group(1)
        text.stylize(LEVEL_STYLES.get(key, ""), m.start(), m.end())
    for m in _STATUS.finditer(line):
        text.stylize(_status_style(m.group(1)), m.start(), m.end())
    for q in _QUOTED.finditer(line):
        text.stylize(_QUOTE_STYLE, q.start(), q.end())
    return text


def _status_style(code: str) -> str:
    if code[0] == "2":
        return "bold bright_green"
    if code[0] == "3":
        return "bold bright_yellow"
    return "bold bright_blue"  # 4xx / 5xx — blue, not an alarming red
