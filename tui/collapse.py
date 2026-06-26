"""Collapse consecutive duplicate log lines in a Textual ``RichLog``.

A :class:`CollapsingWriter` wraps one ``RichLog`` and, when the next line repeats
the previous one (same dedup key), rewrites the last rendered line in place with an
incremented dim ``×N`` counter instead of appending a duplicate. The original log
line is left verbatim; only the dim counter span is added on top.

``RichLog`` has no public edit/replace API, so the in-place rewrite reaches into its
internals (``lines``, ``_start_line``, ``_line_cache``, ``_size_known``). Verified
against textual 8.2.7. The one subtlety is ``max_lines`` trimming: ``write`` drops
strips from the *front* and bumps ``_start_line`` by the number dropped, so the
count of strips our line occupies at the tail is ``Δlen(lines) + Δ_start_line``.
"""

from __future__ import annotations

from rich.text import Text
from textual.widgets import RichLog

from tui.logcolor import with_counter


class CollapsingWriter:
    def __init__(self, widget: RichLog) -> None:
        self._widget = widget
        self._last_key: str | None = None
        self._last_text: Text | None = None  # bare colorized line, no counter
        self._count = 0
        self._last_strips = 0  # strips the current line occupies at the tail

    def _write_counting(self, text: Text, replace_last: bool = False) -> int:
        """Write `text` and return how many tail strips it added (0 if deferred)."""
        w = self._widget
        n0, s0 = len(w.lines), w._start_line
        # A width-aware log records source per logical line so it can re-wrap; tell
        # it this counter rewrite replaces the last line rather than adding one.
        if replace_last and getattr(w, "_records_history", False):
            w.write(text, replace_last=True)
        else:
            w.write(text)
        # A front-trim removes strips from the head and bumps _start_line by that
        # many, so the tail growth is the length delta plus the start-line delta.
        return (len(w.lines) - n0) + (w._start_line - s0)

    def write(self, text: Text, key: str) -> None:
        w = self._widget
        repeat = (
            key == self._last_key
            and self._last_text is not None
            and w._size_known
            and 0 < self._last_strips <= len(w.lines)
        )
        if repeat:
            self._count += 1
            del w.lines[-self._last_strips :]
            w._line_cache.clear()
            self._last_strips = self._write_counting(
                with_counter(self._last_text, self._count), replace_last=True
            )
            w.refresh()
        else:
            self._last_strips = self._write_counting(text)
            self._last_key = key
            self._last_text = text
            self._count = 1

    def reset(self) -> None:
        """Forget the current run (call after the widget is cleared)."""
        self._last_key = None
        self._last_text = None
        self._count = 0
        self._last_strips = 0
