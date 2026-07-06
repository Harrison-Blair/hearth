"""Shared widgets for the monitor TUI.

``ScreenWidthRichLog`` is the width-aware, selectable log pane. ``Stepper`` and
``NavBar`` are the touch-first building blocks for the 320x480 portrait screens:
a numeric field driven by −/+ buttons (typable with a keyboard on desktop) and a
height-3 top bar with a back button, title, and daemon/ollama status dots.
"""

from __future__ import annotations

from collections import deque

from rich.segment import Segment
from rich.style import Style
from rich.text import Text
from textual.containers import Horizontal
from textual.message import Message
from textual.selection import Selection
from textual.strip import Strip
from textual.widgets import Button, Input, RichLog, Static


class ScreenWidthRichLog(RichLog):
    """A RichLog that wraps to its on-screen width and re-wraps on demand.

    Textual's ``RichLog.write`` measures content against ``app.console``, whose
    width is the ``COLUMNS`` env var (default 80) — not the widget's actual size
    — so text wraps at ~80 cols regardless of terminal width. Defaulting
    ``width`` to the live content region makes wrapping track the screen.

    A line written while its screen is hidden has a 0-width content region, so it
    falls back to ``min_width`` and wraps wrong. ``RichLog`` only keeps the
    pre-wrapped strips (no source), so we record each logical line's source and
    :meth:`reflow` re-wraps the backlog to the current width — called when the
    screen or log channel is reselected.
    """

    _records_history = True  # marker CollapsingWriter duck-types on

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        # Source per logical line, capped like the rendered backlog (max_lines).
        self._history: deque = deque(maxlen=self.max_lines)
        self._wrap_width: int | None = None  # width the backlog is wrapped at

    def write(
        self,
        content,
        width=None,
        expand=False,
        shrink=True,
        scroll_end=None,
        animate=False,
        replace_last=False,
    ):
        if width is None:
            region = self.scrollable_content_region.width
            if region:
                width = region
        result = super().write(content, width, expand, shrink, scroll_end, animate)
        # Record only once actually rendered: super() defers writes until the size
        # is known, then replays them through write(), which would double-record.
        if self._size_known:
            if replace_last and self._history:
                self._history[-1] = content  # collapse rewrote the last line in place
            else:
                self._history.append(content)
            self._wrap_width = width or self.scrollable_content_region.width or self.min_width
        return result

    def clear(self):
        self._history.clear()
        self._wrap_width = None
        return super().clear()

    def reflow(self) -> bool:
        """Re-wrap the recorded backlog to the current width. True if it changed."""
        region = self.scrollable_content_region.width
        if not region or not self._history or region == self._wrap_width:
            return False
        entries = list(self._history)
        self.clear()
        for content in entries:
            self.write(content)
        return True

    # ---- text selection support --------------------------------------------

    def get_selection(self, selection: Selection) -> tuple[str, str] | None:
        text = "\n".join(
            "".join(segment.text for segment in strip).rstrip()
            for strip in self.lines
        )
        return selection.extract(text), "\n"

    def selection_updated(self, selection: Selection | None) -> None:
        self._line_cache.clear()
        self.refresh()

    @staticmethod
    def _apply_selection_style(
        strip: Strip, sel_start: int, sel_end: int, style: Style
    ) -> Strip:
        length = strip.cell_length
        if sel_start <= 0 and sel_end >= length:
            return Strip(
                Segment(seg.text, (seg.style or Style()) + style)
                for seg in strip
            )
        parts = []
        if sel_start > 0:
            parts.append(strip.crop(0, sel_start))
        mid = strip.crop(max(0, sel_start), min(sel_end, length))
        parts.append(
            Strip(
                Segment(seg.text, (seg.style or Style()) + style)
                for seg in mid
            )
        )
        if sel_end < length:
            parts.append(strip.crop(sel_end, length))
        return Strip.join(parts)

    def render_line(self, y: int) -> Strip:
        scroll_x, scroll_y = self.scroll_offset
        y_abs = scroll_y + y
        strip = self._render_line(y_abs, scroll_x, self.scrollable_content_region.width)
        strip = strip.apply_offsets(scroll_x, y_abs)
        strip = strip.apply_style(self.rich_style)
        sel = self.text_selection
        if sel is not None:
            if (span := sel.get_span(y_abs)) is not None:
                start, end = span
                if end == -1:
                    end = strip.cell_length
                if start < end:
                    sel_style = self.screen.get_component_rich_style(
                        "screen--selection"
                    )
                    strip = self._apply_selection_style(strip, start, end, sel_style)
        return strip


class Stepper(Horizontal):
    """Touch-first numeric field: ``[ − ][ value ][ + ]``. The value box is also
    a numeric Input so a keyboard (desktop testing) can type an exact value;
    touch never needs it — the buttons remain the primary control."""

    DEFAULT_CSS = """
    Stepper { height: 3; }
    Stepper Button { width: 7; min-width: 7; }
    Stepper .stepper-value {
        width: 1fr; height: 3; border: round $panel; padding: 0 1;
    }
    """

    class Changed(Message):
        def __init__(self, stepper: Stepper, value: float) -> None:
            self.stepper = stepper
            self.value = value
            super().__init__()

        @property
        def control(self) -> Stepper:
            return self.stepper

    def __init__(
        self,
        value: float = 0.0,
        *,
        lo: float = 0.0,
        hi: float = 1.0,
        step: float = 1.0,
        id: str | None = None,  # noqa: A002 - Textual's widget kwarg
    ) -> None:
        super().__init__(id=id)
        self.lo = lo
        self.hi = hi
        self.step_size = step
        self._value = self._clamp(value)

    def _clamp(self, value: float) -> float:
        # Round away float-step noise (0.05 * 3 = 0.15000000000000002).
        return round(max(self.lo, min(self.hi, value)), 9)

    @property
    def value(self) -> float:
        return self._value

    @value.setter
    def value(self, value: float) -> None:
        """Set programmatically (no Changed message)."""
        self._value = self._clamp(value)
        self._render_value()

    @property
    def value_str(self) -> str:
        """The value as config/env text: ints stay ints ("2", not "2.0")."""
        if float(self._value).is_integer():
            return str(int(self._value))
        return f"{self._value:g}"

    def compose(self):
        yield Button("−", classes="stepper-dec")
        yield Input(self.value_str, classes="stepper-value", restrict=r"-?[0-9]*\.?[0-9]*")
        yield Button("+", classes="stepper-inc")

    def _render_value(self) -> None:
        self.query_one(".stepper-value", Input).value = self.value_str

    def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        delta = self.step_size if event.button.has_class("stepper-inc") else -self.step_size
        self._commit(self._value + delta)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        self._commit_typed(event.value)

    def on_input_blurred(self, event: Input.Blurred) -> None:
        event.stop()
        self._commit_typed(event.value)

    def _commit_typed(self, raw: str) -> None:
        try:
            value = float(raw)
        except ValueError:
            self._render_value()  # unparseable ("", "-", "0."): restore the real value
            return
        self._commit(value)
        self._render_value()  # normalize the text (clamping, int formatting)

    def _commit(self, value: float) -> None:
        new = self._clamp(value)
        if new == self._value:
            return
        self._value = new
        self._render_value()
        self.post_message(self.Changed(self, new))


class NavBar(Horizontal):
    """Height-3 top bar: back button, screen title, daemon/ollama status dots."""

    DEFAULT_CSS = """
    NavBar { dock: top; height: 3; }
    NavBar #nav-back { width: 5; min-width: 5; }
    NavBar .nav-title { width: 1fr; height: 3; content-align: center middle; text-style: bold; }
    NavBar .nav-dots { width: 5; height: 3; content-align: right middle; }
    """

    def __init__(self, title: str) -> None:
        super().__init__()
        self._title = title

    def compose(self):
        yield Button("◀", id="nav-back")
        yield Static(self._title, classes="nav-title")
        yield Static("", classes="nav-dots")

    def set_dots(self, daemon_up: bool, ollama_up: bool) -> None:
        dots = Text()
        dots.append("●", style="green" if daemon_up else "red")
        dots.append("●", style="green" if ollama_up else "red")
        self.query_one(".nav-dots", Static).update(dots)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "nav-back":
            event.stop()
            self.app.pop_screen()
