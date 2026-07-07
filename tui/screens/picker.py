"""Full-screen option picker for select fields (touch replacement for Select)."""

from __future__ import annotations

from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.screen import Screen
from textual.widgets import Button, Input, OptionList, Static
from textual.widgets.option_list import Option


class PickerScreen(Screen[str | None]):
    """Pick one value from (label, value) pairs; dismisses with the value or None.

    A filter box narrows a long list (e.g. the ~50 OpenCode Zen models). It is
    never autofocused — touch users scroll/tap the list directly; focusing it
    would pop the on-screen keyboard on every open."""

    DEFAULT_CSS = """
    PickerScreen #picker-title { dock: top; height: 3; content-align: center middle; text-style: bold; }
    PickerScreen #picker-filter { height: 3; }
    PickerScreen OptionList { height: 1fr; }
    PickerScreen #picker-actions { dock: bottom; height: 3; }
    PickerScreen #picker-actions Button { width: 1fr; }
    """

    def __init__(self, title: str, options: list[tuple[str, str]], current: str = "") -> None:
        super().__init__()
        self._title = title
        self._options = options
        self._current = current
        self._visible = list(options)  # options passing the current filter

    def compose(self) -> ComposeResult:
        yield Static(self._title, id="picker-title")
        yield Input(placeholder="filter…", id="picker-filter")
        yield OptionList(id="picker-options")
        with Horizontal(id="picker-actions"):
            yield Button("Cancel", id="picker-cancel")

    def on_mount(self) -> None:
        self._populate()
        # Focus the list, not the filter: touch users tap options directly, and
        # focusing the Input would pop the on-screen keyboard on every open.
        self.query_one("#picker-options", OptionList).focus()

    def _populate(self) -> None:
        """Repaint the OptionList from ``self._visible`` (current-value marked)."""
        opts = self.query_one("#picker-options", OptionList)
        opts.clear_options()
        opts.add_options(
            Option(("● " if value == self._current else "") + label)
            for label, value in self._visible
        )

    @on(Input.Changed, "#picker-filter")
    def _on_filter(self, event: Input.Changed) -> None:
        needle = event.value.strip().lower()
        self._visible = [
            (label, value) for label, value in self._options if needle in label.lower()
        ]
        self._populate()

    @on(OptionList.OptionSelected, "#picker-options")
    def _picked(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(self._visible[event.option_index][1])

    @on(Button.Pressed, "#picker-cancel")
    def _cancel(self) -> None:
        self.dismiss(None)
