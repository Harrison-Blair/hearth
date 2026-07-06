"""Now: the assistant's conversation face, driven by the daemon's state feed.

One screen that morphs by state — a full-bleed colour block that reads across a
room, a big one-word label, a live mic-level meter during listening, the
transcript / reply text, and a recovery banner. The bottom context button
changes meaning by state (Listen / Cancel / Stop). Home (settings/status) is the
◀ back destination via the reused NavBar.
"""

from __future__ import annotations

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Button, Static

from tui.widgets import NavBar

LABELS = {
    "idle": "Idle",
    "listening": "Listening…",
    "thinking": "Thinking…",
    "speaking": "Speaking",
    "no_speech": "No speech",
    "error": "Error",
}

# state -> (button label, control verb, button variant)
CONTEXT = {
    "idle": ("Listen", "LISTEN", "primary"),
    "no_speech": ("Listen", "LISTEN", "primary"),
    "error": ("Listen", "LISTEN", "primary"),
    "listening": ("Cancel", "CANCEL", "error"),
    "thinking": ("Cancel", "CANCEL", "error"),
    "speaking": ("Stop", "STOP", "warning"),
}

DEFAULT_BANNERS = {"no_speech": "Didn't catch that", "error": "Something went wrong"}

METER_CELLS = 30  # single VU row; fits inside 40 cols with padding


class NowScreen(Screen):
    """The daemon's default face; updated by the app's ``_on_state`` handler."""

    DEFAULT_CSS = """
    NowScreen #now-indicator {
        height: 1fr; content-align: center middle; text-style: bold;
    }
    NowScreen #now-indicator.state-idle { background: $panel; color: $text-muted; }
    NowScreen #now-indicator.state-listening { background: $primary; color: $text; }
    NowScreen #now-indicator.state-thinking { background: $warning; color: $text; }
    NowScreen #now-indicator.state-speaking { background: $success; color: $text; }
    NowScreen #now-indicator.state-no_speech { background: $error; color: $text; }
    NowScreen #now-indicator.state-error { background: $error; color: $text; }
    NowScreen #now-meter { height: 1; content-align: center middle; }
    NowScreen #now-transcript { height: 4; padding: 0 1; }
    NowScreen #now-banner { height: 2; padding: 0 1; content-align: center middle; }
    NowScreen #now-context { width: 1fr; height: 3; }
    """

    def __init__(self) -> None:
        super().__init__()
        self._state = "idle"
        self._said = ""
        self._reply = ""

    def compose(self) -> ComposeResult:
        yield NavBar("Assistant")
        with Vertical():
            yield Static(id="now-indicator")
            yield Static(id="now-meter")
            yield Static(id="now-transcript")
            yield Static(id="now-banner")
            yield Button("Listen", id="now-context", variant="primary")

    def on_mount(self) -> None:
        self.set_state("idle")

    def set_state(self, state: str) -> None:
        self._state = state
        indicator = self.query_one("#now-indicator", Static)
        indicator.set_classes([f"state-{state}"])
        indicator.update(LABELS.get(state, state.title()))
        label, _verb, variant = CONTEXT.get(state, CONTEXT["idle"])
        button = self.query_one("#now-context", Button)
        button.label = label
        button.variant = variant
        if state == "listening":  # a fresh turn wipes the previous exchange
            self._said = self._reply = ""
            self._render_transcript()
        self.set_level(0)  # the meter only means anything while listening
        self.set_banner(DEFAULT_BANNERS.get(state, ""))

    def set_level(self, level: int) -> None:
        frac = max(0.0, min(1.0, level / 32767))
        filled = round(frac * METER_CELLS)
        bar = "█" * filled + "▁" * (METER_CELLS - filled)
        self.query_one("#now-meter", Static).update(Text(bar, style="cyan"))

    def set_transcript(self, text: str) -> None:
        self._said = text
        self._render_transcript()

    def set_reply(self, text: str) -> None:
        self._reply = text
        self._render_transcript()

    def _render_transcript(self) -> None:
        out = Text()
        if self._said:
            out.append("you said: ", style="dim")
            out.append(self._said)
        if self._reply:
            if self._said:
                out.append("\n")
            out.append(self._reply, style="italic")
        self.query_one("#now-transcript", Static).update(out)

    def set_banner(self, message: str) -> None:
        self.query_one("#now-banner", Static).update(
            Text(message, style="bold red") if message else Text("")
        )

    @on(Button.Pressed, "#now-context")
    async def _on_context(self) -> None:
        # NB: don't name this `_context` — that shadows Textual's internal
        # MessagePump._context context manager and deadlocks message handling.
        _label, verb, _variant = CONTEXT.get(self._state, CONTEXT["idle"])
        await self.app.supervisor.send(verb)
