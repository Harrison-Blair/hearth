"""Full-screen option picker for select fields (touch replacement for Select)."""

from __future__ import annotations

from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.screen import Screen
from textual.widgets import Button, OptionList, Static
from textual.widgets.option_list import Option


class PickerScreen(Screen[str | None]):
    """Pick one value from (label, value) pairs; dismisses with the value or None."""

    DEFAULT_CSS = """
    PickerScreen #picker-title { dock: top; height: 3; content-align: center middle; text-style: bold; }
    PickerScreen OptionList { height: 1fr; }
    PickerScreen #picker-actions { dock: bottom; height: 3; }
    PickerScreen #picker-actions Button { width: 1fr; }
    """

    def __init__(self, title: str, options: list[tuple[str, str]], current: str = "") -> None:
        super().__init__()
        self._title = title
        self._options = options
        self._current = current

    def compose(self) -> ComposeResult:
        yield Static(self._title, id="picker-title")
        yield OptionList(
            *(
                Option(("● " if value == self._current else "") + label)
                for label, value in self._options
            ),
            id="picker-options",
        )
        with Horizontal(id="picker-actions"):
            yield Button("Cancel", id="picker-cancel")

    @on(OptionList.OptionSelected, "#picker-options")
    def _picked(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(self._options[event.option_index][1])

    @on(Button.Pressed, "#picker-cancel")
    def _cancel(self) -> None:
        self.dismiss(None)
