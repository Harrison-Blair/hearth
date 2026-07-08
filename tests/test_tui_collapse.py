from rich.text import Text
from textual.app import App, ComposeResult
from textual.widgets import RichLog

from tui.collapse import CollapsingWriter


class _LogApp(App):
    def compose(self) -> ComposeResult:
        yield RichLog(max_lines=1000, markup=False, highlight=False, wrap=True, id="log")


async def test_consecutive_duplicates_collapse_in_place():
    app = _LogApp()
    async with app.run_test(size=(80, 24)) as pilot:
        log = app.query_one("#log", RichLog)
        cw = CollapsingWriter(log)
        await pilot.pause()  # let the widget learn its size (writes defer until then)

        for _ in range(3):
            cw.write(Text("reconnecting"), "k")
        await pilot.pause()
        # One logical line, not three — and it carries the ×3 counter.
        assert len(log.lines) == 1
        assert log.lines[0].text.rstrip().endswith("×3")

        # A different line appends fresh, with no counter.
        cw.write(Text("done"), "k2")
        await pilot.pause()
        assert len(log.lines) == 2
        assert log.lines[1].text.rstrip() == "done"


async def test_reset_after_clear_starts_a_new_line():
    app = _LogApp()
    async with app.run_test(size=(80, 24)) as pilot:
        log = app.query_one("#log", RichLog)
        cw = CollapsingWriter(log)
        await pilot.pause()

        cw.write(Text("ping"), "k")
        cw.write(Text("ping"), "k")
        await pilot.pause()
        assert len(log.lines) == 1

        log.clear()
        cw.reset()
        cw.write(Text("ping"), "k")  # same key, but state was reset
        await pilot.pause()
        assert len(log.lines) == 1
        assert "×" not in log.lines[0].text  # fresh line, no stale counter
