from textual import on
from textual.app import App, ComposeResult
from textual.widgets import Static, TabbedContent, TabPane

from tui.app import ScreenWidthRichLog

LONG = "word " * 14  # ~70 chars: one strip at min_width (~78), wraps narrower


class _TabsApp(App):
    """A log in the first (initially active) tab and a second tab to switch to."""

    def compose(self) -> ComposeResult:
        with TabbedContent():
            with TabPane("logs", id="t-logs"):
                yield ScreenWidthRichLog(
                    id="log", markup=False, highlight=False, wrap=True, max_lines=1000
                )
            with TabPane("other", id="t-other"):
                yield Static("other")

    @on(TabbedContent.TabActivated)
    def _reflow(self, event: TabbedContent.TabActivated) -> None:
        pane = event.pane
        if pane is not None:
            self.call_after_refresh(
                lambda: [w.reflow() for w in pane.query(ScreenWidthRichLog)]
            )


async def test_hidden_write_is_rewrapped_on_tab_reselection():
    # Narrow screen so the visible content width is well under min_width.
    async with _TabsApp().run_test(size=(40, 12)) as pilot:
        app = pilot.app
        log = app.query_one("#log", ScreenWidthRichLog)
        await pilot.pause()  # log tab is active and sized

        tabs = app.query_one(TabbedContent)
        tabs.active = "t-other"  # hide the log
        await pilot.pause()

        # Written while hidden: 0-width region → wraps at min_width (one strip).
        log.write(LONG)
        await pilot.pause()
        assert len(log.lines) == 1

        tabs.active = "t-logs"  # reselect → reflow re-wraps to the visible width
        await pilot.pause()
        assert len(log.lines) > 1  # the long line now wraps to the narrow screen


async def test_reflow_is_noop_when_width_unchanged():
    async with _TabsApp().run_test(size=(40, 12)) as pilot:
        app = pilot.app
        log = app.query_one("#log", ScreenWidthRichLog)
        await pilot.pause()

        log.write(LONG)  # written while visible — already wrapped to the screen
        await pilot.pause()
        before = len(log.lines)

        assert log.reflow() is False  # same width → nothing to do
        assert len(log.lines) == before
