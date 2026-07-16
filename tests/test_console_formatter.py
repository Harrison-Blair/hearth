"""Console color formatter (FTHR-016): the console-only `logging.Formatter`
that joins fields with ` │ `, colors timestamp+level by record level (with
the ERROR/CRITICAL color reserved exclusively), dispatches on an optional
`record.category` through a small registry, and auto-suppresses all ANSI
codes when stdout isn't a TTY or `NO_COLOR` is set. Tests use synthetic
`LogRecord`s -- no real category tags exist at any call site yet (that's
FTHR-017/018/019).
"""
from __future__ import annotations

import logging
import re

from hearth.config import LoggingConfig

ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _make_record(level: int, msg: str, category: str | None = None) -> logging.LogRecord:
    record = logging.LogRecord(
        name="test.logger",
        level=level,
        pathname=__file__,
        lineno=1,
        msg=msg,
        args=(),
        exc_info=None,
    )
    if category is not None:
        record.category = category
    return record


def test_delimiter_present_in_every_line():
    from hearth.logging_setup import ColorFormatter

    formatter = ColorFormatter()
    plain = formatter.format(_make_record(logging.INFO, "hello"))
    tagged = formatter.format(_make_record(logging.INFO, "value=1", category="metrics"))

    assert " │ " in plain
    assert " │ " in tagged


def test_error_color_is_exclusive(monkeypatch):
    from hearth.logging_setup import _CATEGORY_COLORS, ColorFormatter

    monkeypatch.setattr("sys.stdout.isatty", lambda: True)
    monkeypatch.delenv("NO_COLOR", raising=False)
    # Register a synthetic category to prove the registry dispatch is
    # covered by the exclusivity check too -- no real category exists yet.
    monkeypatch.setitem(_CATEGORY_COLORS, "demo", lambda message: f"\x1b[36m{message}\x1b[0m")

    formatter = ColorFormatter()

    levels = [
        logging.DEBUG,
        logging.INFO,
        logging.WARNING,
        logging.ERROR,
        logging.CRITICAL,
    ]
    outputs = {
        f"level:{logging.getLevelName(level)}": formatter.format(_make_record(level, "msg"))
        for level in levels
    }
    for category in _CATEGORY_COLORS:
        outputs[f"category:{category}"] = formatter.format(
            _make_record(logging.INFO, "msg", category=category)
        )

    # The reset code ("\x1b[0m") closes out every colored segment regardless
    # of which color opened it -- it isn't itself a color, so exclude it or
    # every colored output would spuriously "share" it with ERROR/CRITICAL.
    reset = "\x1b[0m"
    codes_by_output = {
        key: set(ANSI_RE.findall(value)) - {reset} for key, value in outputs.items()
    }
    error_keys = {"level:ERROR", "level:CRITICAL"}
    error_codes: set[str] = set()
    for key in error_keys:
        error_codes |= codes_by_output[key]
    assert error_codes, "expected ERROR/CRITICAL to carry at least one ANSI code"

    for key, codes in codes_by_output.items():
        if key in error_keys:
            assert codes & error_codes
        else:
            assert not (codes & error_codes), f"{key} leaked the reserved error color: {codes}"


def test_unknown_category_falls_back_to_level_only():
    from hearth.logging_setup import ColorFormatter

    formatter = ColorFormatter()
    unknown = _make_record(logging.INFO, "msg", category="not-a-real-category")
    absent = _make_record(logging.INFO, "msg")
    # Pin identical timestamps so the only variable under test is category
    # handling, not clock drift between the two record constructions.
    absent.created = unknown.created
    absent.msecs = unknown.msecs

    assert formatter.format(unknown) == formatter.format(absent)


def test_no_color_when_not_a_tty(monkeypatch):
    from hearth.logging_setup import ColorFormatter

    monkeypatch.setattr("sys.stdout.isatty", lambda: False)

    formatter = ColorFormatter()
    output = formatter.format(_make_record(logging.ERROR, "boom"))

    assert "\x1b[" not in output
    assert " │ " in output
    assert "boom" in output


def test_no_color_when_no_color_env_set(monkeypatch):
    from hearth.logging_setup import ColorFormatter

    monkeypatch.setattr("sys.stdout.isatty", lambda: True)
    monkeypatch.setenv("NO_COLOR", "1")

    formatter = ColorFormatter()
    output = formatter.format(_make_record(logging.ERROR, "boom"))

    assert "\x1b[" not in output
    assert " │ " in output
    assert "boom" in output


def test_file_handler_unaffected(tmp_path):
    from logging.handlers import RotatingFileHandler

    from hearth.logging_setup import ColorFormatter, setup_logging

    config = LoggingConfig(dir=str(tmp_path), file_name="hearth.log", console=True)
    setup_logging(config)

    root = logging.getLogger()
    file_handler = next(h for h in root.handlers if isinstance(h, RotatingFileHandler))
    assert not isinstance(file_handler.formatter, ColorFormatter)

    logging.getLogger("some.module").error("boom")

    log_text = (tmp_path / "hearth.log").read_text()
    assert "boom" in log_text
    assert " │ " not in log_text
    assert "\x1b[" not in log_text
