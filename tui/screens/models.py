"""Model browser: registry search → detail/tags → pull queue; installed list.

Three screens sized for 40 columns: ``ModelsScreen`` (search + results + pull
progress), ``ModelDetailScreen`` (one model's description and pullable tags,
pushed per selection), and ``InstalledScreen`` (pulled models + delete).
"""

from __future__ import annotations

from rich.text import Text
from textual import events, on
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Input, OptionList, ProgressBar, Static
from textual.widgets.option_list import Option

from tui import discovery
from tui.widgets import NavBar


def _result_meta(m: discovery.RegistryModel) -> str:
    return "   ".join(
        filter(
            None,
            [" · ".join(m.sizes), " ".join(m.capabilities), f"↧{m.pulls}" if m.pulls else ""],
        )
    )


def _result_option(m: discovery.RegistryModel, installed: bool = False) -> Option:
    """A two-line OptionList row for a registry search hit."""
    meta = _result_meta(m)
    text = Text()
    if installed:
        text.append("✓ ", style="green")
    text.append(m.name, style="bold")
    if meta:
        text.append(f"   {meta}", style="dim")
    if m.description:
        desc = m.description if len(m.description) <= 90 else m.description[:90].rstrip() + "…"
        text.append("\n" + desc, style="dim italic")
    return Option(text)


def _registry_detail_text(m: discovery.RegistryModel) -> Text:
    """Full, untruncated detail for the selected registry model."""
    text = Text()
    text.append(m.name, style="bold")
    meta = _result_meta(m)
    if meta:
        text.append(f"\n{meta}", style="dim")
    if m.description:
        text.append(f"\n\n{m.description}")
    return text


def _is_installed(slug: str, installed: set[str]) -> bool:
    # registry slug "qwen2.5" matches pulled "qwen2.5:3b-instruct"
    return any(n == slug or n.startswith(f"{slug}:") for n in installed)


class ModelsScreen(Screen):
    DEFAULT_CSS = """
    ModelsScreen .models-search { height: 3; }
    ModelsScreen .models-search Input { width: 1fr; }
    ModelsScreen .models-search Button { width: 6; min-width: 6; }
    ModelsScreen #search-results { height: 1fr; border: round $panel; }
    ModelsScreen #pull-status { height: 1; color: $text-muted; padding: 0 1; }
    ModelsScreen #pull-progress { height: 1; padding: 0 1; }
    ModelsScreen #pull-queue { height: 1; color: $text-muted; padding: 0 1; }
    ModelsScreen #nav-installed { width: 1fr; }
    ModelsScreen #installed-row { height: 3; }
    """

    def compose(self) -> ComposeResult:
        yield NavBar("Models")
        with Vertical():
            with Horizontal(classes="models-search"):
                yield Input(
                    value=self.app._last_query, id="model-search", placeholder="Search ollama.com…"
                )
                yield Button("Go", id="models-refresh")
            yield OptionList(id="search-results")
            yield Static("", id="pull-status")
            yield ProgressBar(id="pull-progress", total=100, show_eta=False)
            yield Static("", id="pull-queue")
            with Horizontal(id="installed-row"):
                yield Button("Installed", id="nav-installed")

    def on_mount(self) -> None:
        if self.app._last_query:
            self.app.run_worker(
                self.app._do_search(self.app._last_query), group="search", exclusive=True
            )

    def _on_screen_resume(self, event: events.ScreenResume) -> None:
        self.app._refresh_status()  # freshly mounted NavBar dots need a first paint
        # Pick up models pulled out-of-band (e.g. `ollama pull` in a terminal).
        self.app.run_worker(self.app._refresh_installed(), group="installed")

    @on(Input.Submitted, "#model-search")
    def _on_search(self, event: Input.Submitted) -> None:
        self._search(refresh=False)

    @on(Button.Pressed, "#models-refresh")
    def _on_go(self) -> None:
        self._search(refresh=True)
        self.app.run_worker(self.app._refresh_installed(), group="installed")

    def _search(self, *, refresh: bool) -> None:
        query = self.query_one("#model-search", Input).value.strip()
        if query:
            self.app._last_query = query
            self.app.run_worker(
                self.app._do_search(query, refresh=refresh), group="search", exclusive=True
            )

    def render_results(self, results: list[discovery.RegistryModel], installed: set[str]) -> None:
        opts = self.query_one("#search-results", OptionList)
        opts.clear_options()
        if not results:
            opts.add_option(Option("(no results — is ollama.com reachable?)", disabled=True))
            return
        opts.add_options(_result_option(m, _is_installed(m.name, installed)) for m in results)

    def set_pull_status(self, status: str, percent: float | None, queued: list[str]) -> None:
        self.query_one("#pull-status", Static).update(status)
        if percent is not None:
            self.query_one("#pull-progress", ProgressBar).update(total=100, progress=percent)
        self.query_one("#pull-queue", Static).update(
            f"queued: {', '.join(queued)}" if queued else ""
        )

    @on(OptionList.OptionSelected, "#search-results")
    def _on_result_selected(self, event: OptionList.OptionSelected) -> None:
        if self.app._search_results:
            self.app._open_model_detail(self.app._search_results[event.option_index])

    @on(Button.Pressed, "#nav-installed")
    def _open_installed(self) -> None:
        self.app.push_screen("installed")


class ModelDetailScreen(Screen):
    """One registry model: description + pullable tags. Created per selection."""

    DEFAULT_CSS = """
    ModelDetailScreen #registry-detail { height: auto; max-height: 9; padding: 0 1; }
    ModelDetailScreen #model-tags { height: 1fr; border: round $panel; }
    ModelDetailScreen #detail-actions { dock: bottom; height: 3; }
    ModelDetailScreen #model-install { width: 1fr; }
    """

    def __init__(self, model: discovery.RegistryModel, tags: list[discovery.RegistryTag]) -> None:
        super().__init__()
        self._model = model
        self._tags = tags
        self._selected_ref: str | None = None

    def compose(self) -> ComposeResult:
        yield NavBar(self._model.name)
        yield Static(_registry_detail_text(self._model), id="registry-detail")
        tags = OptionList(id="model-tags")
        if self._tags:
            installed = {m.name for m in self.app._installed}
            tags.add_options(
                Option(f"{'✓ ' if t.ref in installed else ''}{t.ref}   {t.size}".rstrip())
                for t in self._tags
            )
        else:
            tags.add_option(Option(f"(no tags found for {self._model.name})", disabled=True))
        yield tags
        with Horizontal(id="detail-actions"):
            yield Button("Install (pick a tag)", id="model-install", variant="success", disabled=True)

    @on(OptionList.OptionSelected, "#model-tags")
    def _on_tag_selected(self, event: OptionList.OptionSelected) -> None:
        if not self._tags:
            return
        self._selected_ref = self._tags[event.option_index].ref
        button = self.query_one("#model-install", Button)
        button.label = f"Install {self._selected_ref}"
        button.disabled = False

    @on(Button.Pressed, "#model-install")
    def _on_install(self) -> None:
        if self._selected_ref:
            self.app._enqueue_pull(self._selected_ref)
            self.app.pop_screen()  # back to Models, where pull progress shows


class InstalledScreen(Screen):
    DEFAULT_CSS = """
    InstalledScreen #installed-list { height: 1fr; border: round $panel; }
    InstalledScreen #installed-actions { dock: bottom; height: 3; }
    InstalledScreen #model-delete { width: 1fr; }
    """

    def compose(self) -> ComposeResult:
        yield NavBar("Installed")
        yield OptionList(id="installed-list")
        with Horizontal(id="installed-actions"):
            yield Button("Delete selected", id="model-delete", variant="error")

    def _on_screen_resume(self, event: events.ScreenResume) -> None:
        self.app._refresh_status()
        self.app.run_worker(self.app._refresh_installed(), group="installed")

    def render_installed(self, models: list[discovery.OllamaModel]) -> None:
        opts = self.query_one("#installed-list", OptionList)
        opts.clear_options()
        for m in models:
            meta = " · ".join(p for p in (m.human_size if m.size else "", m.parameter_size) if p)
            opts.add_option(Option(f"{m.name}   {meta}".rstrip()))

    @on(Button.Pressed, "#model-delete")
    async def _on_delete(self) -> None:
        idx = self.query_one("#installed-list", OptionList).highlighted
        if idx is not None and self.app._installed:
            await self.app._delete_model(self.app._installed[idx].name)
