from textual import on
from textual.app import App, ComposeResult
from textual.events import TextSelected
from textual.selection import Selection

from tui.app import ScreenWidthRichLog


class _TestApp(App):
    def compose(self) -> ComposeResult:
        yield ScreenWidthRichLog(
            id="log", markup=False, highlight=False, wrap=False, max_lines=1000
        )

    @on(TextSelected)
    async def _copy(self) -> None:
        text = self.screen.get_selected_text()
        if text:
            self.copy_to_clipboard(text)
            copied = getattr(self, "copied", None)
            if copied is not None:
                copied.append(text)


async def test_drag_produces_precise_selection_not_select_all():
    async with _TestApp().run_test(size=(60, 10)) as pilot:
        log = pilot.app.query_one("#log", ScreenWidthRichLog)
        for i in range(6):
            log.write(f"line {i:02d} content here")
        await pilot.pause()

        await pilot.mouse_down("#log", offset=(2, 1))
        await pilot.mouse_up("#log", offset=(15, 3))
        await pilot.pause()

        sels = dict(pilot.app.screen.selections)
        assert "log" in {w.id for w in sels}
        sel = sels[log]
        assert sel != Selection(None, None), "drag must produce a precise range, not SELECT_ALL"
        assert sel.start is not None and sel.end is not None


async def test_get_selected_text_returns_only_dragged_region():
    async with _TestApp().run_test(size=(60, 10)) as pilot:
        log = pilot.app.query_one("#log", ScreenWidthRichLog)
        for i in range(6):
            log.write(f"line {i:02d} content here")
        await pilot.pause()

        await pilot.mouse_down("#log", offset=(2, 1))
        await pilot.mouse_up("#log", offset=(15, 3))
        await pilot.pause()

        text = pilot.app.screen.get_selected_text()
        assert text is not None
        assert "line 01" not in text, "should only include from offset 2 onward"
        assert "ne 01 content here" in text
        assert "line 04 content here" not in text


async def test_auto_copy_on_highlight_fires_text_selected():
    async with _TestApp().run_test(size=(60, 10)) as pilot:
        pilot.app.copied = []
        log = pilot.app.query_one("#log", ScreenWidthRichLog)
        for i in range(4):
            log.write(f"line {i:02d}")
        await pilot.pause()

        await pilot.mouse_down("#log", offset=(0, 1))
        await pilot.mouse_up("#log", offset=(5, 2))
        await pilot.pause()

        assert len(pilot.app.copied) == 1
        assert "line 01" in pilot.app.copied[0]
