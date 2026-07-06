"""Home: status panel + full-width navigation and daemon controls."""

from __future__ import annotations

from textual import on
from textual.app import ComposeResult
from textual.containers import Horizontal, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Static


class HomeScreen(Screen):
    """Everything reachable in one tap; status readable at a glance."""

    DEFAULT_CSS = """
    HomeScreen VerticalScroll { padding: 0 1; }
    HomeScreen #home-status { height: 5; padding: 0 1; margin-bottom: 1; }
    HomeScreen Button { width: 1fr; }
    HomeScreen Horizontal { height: 3; }
    HomeScreen #vol-value { width: 7; height: 3; content-align: center middle; }
    HomeScreen #vol-down, HomeScreen #vol-up { width: 7; min-width: 7; }
    """

    def compose(self) -> ComposeResult:
        with VerticalScroll():
            yield Static(id="home-status")
            with Horizontal():
                yield Button("Now", id="nav-now")
            with Horizontal():
                yield Button("Logs", id="nav-logs")
            with Horizontal():
                yield Button("Config", id="nav-config")
            with Horizontal():
                yield Button("Models", id="nav-models")
            with Horizontal():
                yield Button("Stop", id="btn-toggle-daemon", variant="error")
                yield Button("Restart", id="btn-restart")
            with Horizontal():
                yield Button("Restart LLM", id="btn-ollama-restart", variant="warning")
            with Horizontal():
                yield Button("Mute", id="vol-mute", variant="warning")
                yield Button("−", id="vol-down")
                yield Static("", id="vol-value")
                yield Button("+", id="vol-up")

    @on(Button.Pressed, "#nav-now")
    def _nav_now(self) -> None:
        self.app.push_screen("now")

    @on(Button.Pressed, "#nav-logs")
    def _nav_logs(self) -> None:
        self.app.push_screen("logs")

    @on(Button.Pressed, "#nav-config")
    def _nav_config(self) -> None:
        self.app.push_screen("config")

    @on(Button.Pressed, "#nav-models")
    def _nav_models(self) -> None:
        self.app.push_screen("models")

    @on(Button.Pressed, "#btn-toggle-daemon")
    async def _toggle_daemon(self) -> None:
        if self.app.supervisor.running:
            await self.app._on_stop()
        else:
            await self.app._on_start()

    @on(Button.Pressed, "#btn-restart")
    async def _restart(self) -> None:
        await self.app._restart()

    @on(Button.Pressed, "#btn-ollama-restart")
    async def _restart_llm(self) -> None:
        await self.app._on_ollama_restart()

    @on(Button.Pressed, "#vol-mute")
    async def _mute(self) -> None:
        await self.app._on_mute()

    @on(Button.Pressed, "#vol-down")
    async def _vol_down(self) -> None:
        await self.app._nudge_volume(-0.05)

    @on(Button.Pressed, "#vol-up")
    async def _vol_up(self) -> None:
        await self.app._nudge_volume(+0.05)
