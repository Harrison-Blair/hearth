"""Voice browser: pick an English Piper voice from the catalog and download it.

Sized for the 320x480 portrait (≈40x30 cell) touch display: no search box — the
English catalog is small enough to scroll — a full-height option list, a combined
progress bar, and one full-width Download button. Downloaded voices land in
``models/piper/`` and become selectable in the Config voice picker.
"""

from __future__ import annotations

from rich.text import Text
from textual import events, on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, OptionList, ProgressBar, Static
from textual.widgets.option_list import Option

from tui import discovery
from tui.widgets import NavBar


def _voice_option(v: discovery.RegistryVoice) -> Option:
    text = Text()
    if v.installed:
        text.append("✓ ", style="green")
    text.append(v.key, style="bold")
    text.append(f"\n{v.quality} · {v.num_speakers}spk · {v.size_bytes // 1_000_000}MB", style="dim")
    return Option(text)


class VoicesScreen(Screen):
    DEFAULT_CSS = """
    VoicesScreen #voice-list { height: 1fr; border: round $panel; }
    VoicesScreen #voice-dl-status { height: 1; color: $text-muted; padding: 0 1; }
    VoicesScreen #voice-dl-progress { height: 1; padding: 0 1; }
    VoicesScreen #voice-actions { dock: bottom; height: 3; }
    VoicesScreen #voice-download { width: 1fr; }
    """

    def __init__(self) -> None:
        super().__init__()
        self._selected: discovery.RegistryVoice | None = None

    def compose(self) -> ComposeResult:
        yield NavBar("Voices")
        with Vertical():
            yield OptionList(id="voice-list")
            yield Static("", id="voice-dl-status")
            yield ProgressBar(id="voice-dl-progress", total=100, show_eta=False)
        with Horizontal(id="voice-actions"):
            yield Button("Download (pick one)", id="voice-download", variant="success", disabled=True)

    def on_mount(self) -> None:
        self.app.run_worker(self.app._load_voice_catalog(), group="voice-catalog")

    def _on_screen_resume(self, event: events.ScreenResume) -> None:
        self.app._refresh_status()  # freshly mounted NavBar dots need a first paint
        self.app.run_worker(self.app._load_voice_catalog(), group="voice-catalog")

    def render_catalog(self, voices: list[discovery.RegistryVoice]) -> None:
        opts = self.query_one("#voice-list", OptionList)
        opts.clear_options()
        if not voices:
            opts.add_option(Option("(catalog unavailable — is huggingface.co reachable?)",
                                   disabled=True))
            return
        opts.add_options(_voice_option(v) for v in voices)

    def set_download_status(self, status: str, percent: float | None) -> None:
        self.query_one("#voice-dl-status", Static).update(status)
        if percent is not None:
            self.query_one("#voice-dl-progress", ProgressBar).update(total=100, progress=percent)

    @on(OptionList.OptionSelected, "#voice-list")
    def _on_voice_selected(self, event: OptionList.OptionSelected) -> None:
        if not self.app._voice_catalog:
            return
        self._selected = self.app._voice_catalog[event.option_index]
        button = self.query_one("#voice-download", Button)
        button.label = f"Download {self._selected.key}"
        button.disabled = False

    @on(Button.Pressed, "#voice-download")
    def _on_download(self) -> None:
        if self._selected:
            self.app.run_worker(self.app._do_voice_download(self._selected), group="voice-dl")
