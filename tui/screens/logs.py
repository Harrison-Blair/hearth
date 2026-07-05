"""Logs: one log pane with App/LLM/Ollama channel buttons.

All three ``ScreenWidthRichLog`` widgets are always mounted (the app's pumps
write to them whether or not this screen is showing); only the active channel
is displayed. Switching channels or resuming the screen re-wraps the backlog
to the on-screen width and resets the channel's CollapsingWriter, whose tail
bookkeeping is stale after a re-wrap.
"""

from __future__ import annotations

from textual import events, on
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.screen import ModalScreen, Screen
from textual.widgets import Button, Input

from tui.widgets import ScreenWidthRichLog

MAX_LOG_LINES = 1000

CHANNELS = ("app", "llm", "ollama")


class LogsScreen(Screen):
    BINDINGS = [("t", "chat", "chat")]  # desktop-only: type a command as speech

    DEFAULT_CSS = """
    LogsScreen #logs-nav { dock: top; height: 3; }
    LogsScreen #logs-nav Button { min-width: 4; width: 1fr; }
    LogsScreen #logs-back, LogsScreen #logs-clear { max-width: 5; }
    LogsScreen #logs-nav .channel-active { background: $primary; color: $text; }
    LogsScreen ScreenWidthRichLog { height: 1fr; }
    LogsScreen ScreenWidthRichLog.hidden-channel { display: none; }
    """

    def __init__(self) -> None:
        super().__init__()
        self.active_channel = "app"

    def compose(self) -> ComposeResult:
        with Horizontal(id="logs-nav"):
            yield Button("◀", id="logs-back")
            yield Button("App", id="chan-app", classes="channel-active")
            yield Button("LLM", id="chan-llm")
            yield Button("Olma", id="chan-ollama")
            yield Button("✕", id="logs-clear")
        for name in CHANNELS:
            yield ScreenWidthRichLog(
                id=f"{name}log",
                highlight=False,
                markup=False,
                wrap=True,
                max_lines=MAX_LOG_LINES,
                classes="" if name == "app" else "hidden-channel",
            )

    def log_widget(self, channel: str) -> ScreenWidthRichLog:
        return self.query_one(f"#{channel}log", ScreenWidthRichLog)

    def on_mount(self) -> None:
        self.app._attach_logs(self)

    @on(Button.Pressed, "#logs-back")
    def _back(self) -> None:
        self.app.pop_screen()

    @on(Button.Pressed, "#logs-clear")
    def _clear(self) -> None:
        self.app._clear_logs()

    @on(Button.Pressed, "#chan-app")
    def _show_app(self) -> None:
        self.show_channel("app")

    @on(Button.Pressed, "#chan-llm")
    def _show_llm(self) -> None:
        self.show_channel("llm")

    @on(Button.Pressed, "#chan-ollama")
    def _show_ollama(self) -> None:
        self.show_channel("ollama")

    def show_channel(self, channel: str) -> None:
        self.active_channel = channel
        for name in CHANNELS:
            self.log_widget(name).set_class(name != channel, "hidden-channel")
            self.query_one(f"#chan-{name}", Button).set_class(
                name == channel, "channel-active"
            )
        self.call_after_refresh(self._reflow_active)

    def _on_screen_resume(self, event: events.ScreenResume) -> None:
        # Lines written while this screen was covered wrapped at a stale width.
        self.call_after_refresh(self._reflow_active)

    def _reflow_active(self) -> None:
        widget = self.log_widget(self.active_channel)
        if widget.reflow():
            self.app._reset_writer(self.active_channel)

    def action_chat(self) -> None:
        self.app.push_screen(ChatModal())


class ChatModal(ModalScreen):
    """Desktop-testing helper: type a command that the daemon treats as speech."""

    DEFAULT_CSS = """
    ChatModal { align: center middle; }
    ChatModal Input { width: 90%; }
    """

    def compose(self) -> ComposeResult:
        yield Input(id="chat", placeholder="Type a command (sent as speech)…")

    @on(Input.Submitted, "#chat")
    async def _submit(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        self.dismiss(None)
        if text:
            await self.app._send_text(text)

    def on_key(self, event: events.Key) -> None:
        if event.key == "escape":
            self.dismiss(None)
