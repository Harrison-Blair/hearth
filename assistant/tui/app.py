"""Textual monitor TUI for the assistant daemon.

Supervises ``python -m assistant.app`` as a child, streams its logs into Logs/LLM
tabs, edits config via ``ASSISTANT_*`` env overrides (applied on restart), and
drives the live daemon over its stdin control channel: a chat box that mimics
transcribed speech, and instant mute/volume. Laid out for a 3.5" 480x320
touchscreen — tabbed views, big tappable buttons.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import re
from typing import TYPE_CHECKING

from textual import on
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from rich.text import Text
from textual.widgets import (
    Button,
    Input,
    Label,
    OptionList,
    ProgressBar,
    RichLog,
    Select,
    SelectionList,
    Static,
    TabbedContent,
    TabPane,
    TextArea,
)
from textual.widgets.option_list import Option
from textual.widgets.selection_list import Selection

from assistant.wake import registry
from assistant.tui import configfile, discovery, envfile
from assistant.tui.config_schema import FIELDS, Field, changed_fields, coerce, overrides_for
from assistant.tui.logcolor import colorize_line, colorize_message
from assistant.tui.logparse import parse
from assistant.tui.supervisor import ENV_FILE, DaemonSupervisor, free_ollama_port

if TYPE_CHECKING:
    from assistant.core.config import Config

log = logging.getLogger(__name__)

VOLUME_ENV = "ASSISTANT_AUDIO__OUTPUT_VOLUME"
VOLUME_PRESETS = [("25%", 0.25), ("50%", 0.5), ("75%", 0.75), ("100%", 1.0)]
MAX_LOG_LINES = 1000
ENV_EXAMPLE_FILE = "env.example"
HEALTH_POLL_SECONDS = 5.0


def _field_id(field: Field) -> str:
    return "field-" + "_".join(field.key)


def _as_option(item: object) -> tuple[str, str]:
    """Normalize a select provider result item to a (label, value) pair.

    Providers may yield bare strings (label == value) or (label, value) tuples."""
    if isinstance(item, tuple):
        label, value = item
        return str(label), str(value)
    return str(item), str(item)


def _default_query(model: str) -> str:
    """Seed the registry search with the family of the configured model.

    e.g. "qwen2.5:3b-instruct" -> "qwen"."""
    m = re.match(r"[A-Za-z]+", model or "")
    return m.group(0) if m else "qwen"


def _result_meta(m: "discovery.RegistryModel") -> str:
    return "   ".join(
        filter(None, [" · ".join(m.sizes), " ".join(m.capabilities), f"↧{m.pulls}" if m.pulls else ""])
    )


def _result_option(m: "discovery.RegistryModel", installed: bool = False) -> Option:
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


def _registry_detail_text(m: "discovery.RegistryModel") -> Text:
    """Full, untruncated detail for the selected registry model."""
    text = Text()
    text.append(m.name, style="bold")
    meta = _result_meta(m)
    if meta:
        text.append(f"\n{meta}", style="dim")
    if m.description:
        text.append(f"\n\n{m.description}")
    return text


class ScreenWidthRichLog(RichLog):
    """A RichLog that wraps to its on-screen width.

    Textual's ``RichLog.write`` measures content against ``app.console``, whose
    width is the ``COLUMNS`` env var (default 80) — not the widget's actual size
    — so text wraps at ~80 cols regardless of terminal width. Defaulting
    ``width`` to the live content region makes wrapping track the screen.
    """

    def write(
        self, content, width=None, expand=False, shrink=True, scroll_end=None, animate=False
    ):
        if width is None:
            region = self.scrollable_content_region.width
            if region:
                width = region
        return super().write(content, width, expand, shrink, scroll_end, animate)


class AssistantTUI(App):
    CSS = """
    #status { dock: top; height: 1; background: $boost; color: $text; padding: 0 1; }
    Button { padding: 0 2; }
    #buttons { dock: bottom; height: 3; align: center middle; }
    #buttons Button { margin: 0 1; min-width: 10; }
    RichLog { background: $surface; }
    .volume-row { height: 3; align: left middle; }
    .volume-row Button { margin: 0 1; min-width: 8; }
    .llm-row { height: 3; align: left middle; }
    .llm-row Button { margin: 0 1; }
    #ollama-status { padding: 0 1; content-align: left middle; height: 3; }
    .field-row { height: 3; }
    .field-row Label { width: 22; content-align: left middle; height: 3; }
    #model-detail { height: auto; padding: 0 1; color: $text-muted; }
    /* Expand to fit the options; cap at ~10 rows and scroll the rest. */
    #field-wake_model_paths { height: auto; max-height: 12; border: round $panel; margin-bottom: 1; }
    #wake-phrases { height: auto; padding: 0 1; color: $text-muted; }
    .models-search { height: 3; }
    .models-search Input { width: 1fr; }
    .models-search Button { margin: 0 1; }
    #search-results { height: 8; border: round $panel; }
    #model-tags { height: 6; border: round $panel; }
    #installed-list { height: 6; border: round $panel; }
    #pull-status { padding: 0 1; color: $text-muted; }
    #pull-queue { padding: 0 1; color: $text-muted; }
    #pull-progress { height: 1; }
    .install-row { height: auto; }
    .install-col { width: 1fr; height: auto; }
    #registry-detail { width: 1fr; height: auto; border: round $panel; padding: 0 1; color: $text-muted; }
    .env-buttons { dock: top; height: 3; align: center middle; }
    .env-buttons Button { margin: 0 1; min-width: 8; }
    .config-buttons { height: 3; align: center middle; }
    .config-buttons Button { margin: 0 1; min-width: 8; }
    #envedit { height: 1fr; }
    #chat { dock: bottom; }
    """

    def __init__(
        self,
        supervisor: DaemonSupervisor | None = None,
        ollama: DaemonSupervisor | None = None,
    ) -> None:
        super().__init__()
        self.supervisor = supervisor or DaemonSupervisor()
        self._config = discovery.current_config()
        # The LLM server (Ollama) is managed on demand via the "Restart LLM"
        # button; the argv is config-driven (default `ollama serve`).
        self.ollama = ollama or DaemonSupervisor(list(self._config.llm.serve_cmd))
        self._overrides: dict[str, str] = {}
        self._state = "stopped"
        self._ollama_up = False
        self._volume = self._config.audio.output_volume
        self._muted = self._volume == 0.0
        self._last_volume = self._volume or 1.0
        # Models tab: registry browsing + a sequential pull queue.
        self._search_results: list[discovery.RegistryModel] = []
        self._tags: list[discovery.RegistryTag] = []
        self._installed: list[discovery.OllamaModel] = []
        self._pull_queue: list[str] = []
        self._pulling = False
        self._last_query = _default_query(self._config.llm.model)
        self._selected_ref: str | None = None

    # ---- layout --------------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Static(id="status")
        with TabbedContent():
            with TabPane("Logs", id="tab-logs"):
                yield ScreenWidthRichLog(
                    id="applog", highlight=False, markup=False, wrap=True, max_lines=MAX_LOG_LINES
                )
            with TabPane("Ollama", id="tab-ollama"):
                yield ScreenWidthRichLog(
                    id="ollamalog",
                    highlight=False,
                    markup=False,
                    wrap=True,
                    max_lines=MAX_LOG_LINES,
                )
            with TabPane("LLM", id="tab-llm"):
                yield ScreenWidthRichLog(
                    id="llmlog", highlight=False, markup=False, wrap=True, max_lines=MAX_LOG_LINES
                )
                yield Input(id="chat", placeholder="Type a command (sent as speech)…")
            with TabPane("Config", id="tab-config"):
                yield from self._compose_config()
            with TabPane("Env", id="tab-env"):
                yield from self._compose_env()
            with TabPane("Models", id="tab-models"):
                yield from self._compose_models()
        with Horizontal(id="buttons"):
            yield Button("Start", id="btn-start", variant="success")
            yield Button("Stop", id="btn-stop", variant="error")
            yield Button("Restart", id="btn-restart")
            yield Button("Apply & Restart", id="btn-apply", variant="primary")
            yield Button("Restart LLM", id="btn-ollama-restart", variant="warning")
            yield Button("Clear", id="btn-clear")

    def _compose_config(self) -> ComposeResult:
        with VerticalScroll():
            with Horizontal(classes="config-buttons"):
                yield Button("Save", id="config-save", variant="primary")
                yield Button("Reset to default", id="config-reset", variant="warning")
            with Horizontal(classes="volume-row"):
                yield Button("Unmute" if self._muted else "Mute", id="vol-mute", variant="warning")
                for label, _ in VOLUME_PRESETS:
                    yield Button(label, id=f"vol-{int(_ * 100)}")
            with Horizontal(classes="llm-row"):
                yield Static("ollama: …", id="ollama-status")
            for field in FIELDS:
                if field.kind == "multiselect":
                    # Full-width so the checkbox list can show many options and scroll,
                    # rather than being clipped into a one-line field row.
                    yield Label(field.label)
                    yield self._field_widget(field)
                    yield Static(id="wake-phrases")
                    continue
                with Horizontal(classes="field-row"):
                    yield Label(field.label)
                    yield self._field_widget(field)
            yield Static(id="model-detail")

    def _field_widget(self, field: Field):
        wid = _field_id(field)
        if field.kind == "multiselect":
            # Options and selection are filled in on mount (discovered live).
            return SelectionList(id=wid)
        current = discovery.current_value(self._config, field.key)
        if field.kind == "select":
            # Options are filled in on mount (some are discovered live).
            return Select([(current, current)] if current else [], id=wid, allow_blank=True)
        return Input(value=current, id=wid)

    def _compose_env(self) -> ComposeResult:
        with Horizontal(classes="env-buttons"):
            yield Button("Save", id="env-save", variant="primary")
            yield Button("Add missing", id="env-add")
            yield Button("Remove extra", id="env-remove", variant="warning")
            yield Button("Reload", id="env-reload")
        yield TextArea(id="envedit")

    def _compose_models(self) -> ComposeResult:
        with VerticalScroll():
            with Horizontal(classes="models-search"):
                yield Input(
                    value=self._last_query, id="model-search", placeholder="Search ollama.com…"
                )
                yield Button("Refresh", id="models-refresh")
            yield OptionList(id="search-results")
            yield OptionList(id="model-tags")
            with Horizontal(classes="install-row"):
                with Vertical(classes="install-col"):
                    yield Button("Install selected", id="model-install", variant="success")
                    yield Static("", id="pull-status")
                    yield ProgressBar(id="pull-progress", total=100, show_eta=False)
                    yield Static("", id="pull-queue")
                yield Static("", id="registry-detail")
            yield Label("Installed")
            yield OptionList(id="installed-list")
            yield Button("Delete selected", id="model-delete", variant="error")

    # ---- lifecycle -----------------------------------------------------------

    async def on_mount(self) -> None:
        self._applog = self.query_one("#applog", RichLog)
        self._llmlog = self.query_one("#llmlog", RichLog)
        self._ollamalog = self.query_one("#ollamalog", RichLog)
        self.query_one("#envedit", TextArea).text = envfile.read(ENV_FILE)
        self.run_worker(self._populate_selects(), group="selects")
        self.run_worker(self._refresh_installed(), group="installed")
        if self._last_query:
            self.run_worker(self._do_search(self._last_query), group="search", exclusive=True)
        self.run_worker(self._startup(), group="startup")
        self.run_worker(self._health_loop(), group="health")

    @on(TabbedContent.TabActivated, pane="#tab-models")
    def _on_models_tab(self) -> None:
        # Pick up models pulled out-of-band (e.g. `ollama pull` in a terminal).
        self.run_worker(self._refresh_installed(), group="installed")

    @on(TabbedContent.TabActivated, pane="#tab-config")
    def _on_config_tab(self) -> None:
        # Pick up models installed since mount (via the Models tab or `ollama pull`)
        # so the LLM model dropdown always reflects what's currently installed.
        self.run_worker(self._populate_selects(), group="selects")

    async def _startup(self) -> None:
        await self._start_daemon()
        await self._ensure_ollama()

    async def _populate_selects(self, config: Config | None = None) -> None:
        cfg = config or self._config
        host = cfg.llm.host
        for field in FIELDS:
            if field.kind not in ("select", "multiselect") or field.options is None:
                continue
            try:
                result = field.options(host=host)
                if inspect.isawaitable(result):
                    result = await result
            except Exception as exc:  # noqa: BLE001 - discovery is best-effort
                log.warning("option discovery for %s failed: %s", field.key, exc)
                result = []
            if field.kind == "multiselect":
                self._populate_multiselect(field, cfg, result)
                continue
            current = discovery.current_value(cfg, field.key)
            pairs = [_as_option(item) for item in result]
            if current and current not in [value for _, value in pairs]:
                pairs.insert(0, (current, current))
            select = self.query_one(f"#{_field_id(field)}", Select)
            select.set_options(pairs)
            if current:
                select.value = current
        self._refresh_wake_phrases()

    def _populate_multiselect(self, field: Field, cfg: Config, result: list) -> None:
        # Pre-check whatever the effective config actually loads (model_refs honours
        # the model_paths > model_path > model_name precedence).
        current = set(cfg.wake.model_refs())
        sel = self.query_one(f"#{_field_id(field)}", SelectionList)
        sel.clear_options()
        sel.add_options(
            Selection(label, value, value in current)
            for label, value in (_as_option(item) for item in result)
        )

    def _refresh_wake_phrases(self) -> None:
        """Update the read-only line listing the phrases the checked models wake on."""
        try:
            sel = self.query_one("#field-wake_model_paths", SelectionList)
        except Exception:  # noqa: BLE001 - not mounted yet
            return
        phrases = registry.phrases_for(list(sel.selected))
        text = ", ".join(phrases) if phrases else "(no wake models selected)"
        self.query_one("#wake-phrases", Static).update(f"Wake phrases: {text}")

    @on(SelectionList.SelectedChanged, "#field-wake_model_paths")
    def _on_wake_models_changed(self) -> None:
        self._refresh_wake_phrases()

    # ---- model detail --------------------------------------------------------

    @on(Select.Changed, "#field-llm_model")  # _field_id(("llm", "model"))
    def _on_model_selected(self, event: Select.Changed) -> None:
        detail = self.query_one("#model-detail", Static)
        if event.value in (None, Select.BLANK):
            detail.update("")
            return
        name = str(event.value)
        detail.update(f"Loading details for {name}…")
        self.run_worker(self._show_model_detail(name), group="model-detail", exclusive=True)

    async def _show_model_detail(self, name: str) -> None:
        host = self._config.llm.host
        info = await discovery.ollama_model_detail(host, name)
        detail = self.query_one("#model-detail", Static)
        if info is None:
            # Distinguish a down server from a model that genuinely has no details.
            if await discovery.ollama_health(host):
                detail.update(f"{name}: details unavailable")
            else:
                detail.update("Ollama not running — start the server to see model details")
            return
        parts = [
            f"{info.parameter_count / 1e9:.1f}B params" if info.parameter_count else "params ?",
            f"{info.context_length:,} ctx" if info.context_length else "ctx ?",
        ]
        if info.quantization:
            parts.append(info.quantization)
        if info.family:
            parts.append(info.family)
        caps = ", ".join(info.capabilities) if info.capabilities else "—"
        detail.update(f"{name}: {' · '.join(parts)}  |  capabilities: {caps}")

    # ---- models tab (registry search / pull queue / installed) ---------------

    @on(Input.Submitted, "#model-search")
    async def _on_model_search(self, event: Input.Submitted) -> None:
        self._last_query = event.value.strip()
        if self._last_query:
            self.run_worker(self._do_search(self._last_query), group="search", exclusive=True)

    @on(Button.Pressed, "#models-refresh")
    async def _on_models_refresh(self) -> None:
        if self._last_query:
            self.run_worker(
                self._do_search(self._last_query, refresh=True), group="search", exclusive=True
            )
        self.run_worker(self._refresh_installed(), group="installed")

    async def _do_search(self, query: str, *, refresh: bool = False) -> None:
        results = await discovery.search_registry(query, refresh=refresh)
        self._search_results = results
        self._tags = []
        self.query_one("#model-tags", OptionList).clear_options()
        if not results:
            opts = self.query_one("#search-results", OptionList)
            opts.clear_options()
            opts.add_option(Option("(no results — is ollama.com reachable?)", disabled=True))
            return
        self._render_search_results()

    def _installed_names(self) -> set[str]:
        return {m.name for m in self._installed}

    @staticmethod
    def _is_installed(slug: str, installed: set[str]) -> bool:
        # registry slug "qwen2.5" matches pulled "qwen2.5:3b-instruct"
        return any(n == slug or n.startswith(f"{slug}:") for n in installed)

    def _render_search_results(self) -> None:
        opts = self.query_one("#search-results", OptionList)
        opts.clear_options()
        installed = self._installed_names()
        opts.add_options(
            _result_option(m, self._is_installed(m.name, installed)) for m in self._search_results
        )

    def _render_tags(self) -> None:
        opts = self.query_one("#model-tags", OptionList)
        opts.clear_options()
        installed = self._installed_names()
        opts.add_options(
            Option(f"{'✓ ' if t.ref in installed else ''}{t.ref}   {t.size}".rstrip())
            for t in self._tags
        )

    @on(OptionList.OptionSelected, "#search-results")
    def _on_result_selected(self, event: OptionList.OptionSelected) -> None:
        if not self._search_results:
            return
        m = self._search_results[event.option_index]
        self.query_one("#registry-detail", Static).update(_registry_detail_text(m))
        self.run_worker(self._load_tags(m.name), group="tags", exclusive=True)

    async def _load_tags(self, name: str) -> None:
        tags = await discovery.registry_tags(name)
        self._tags = tags
        if not tags:
            opts = self.query_one("#model-tags", OptionList)
            opts.clear_options()
            opts.add_option(Option(f"(no tags found for {name})", disabled=True))
            return
        self._render_tags()

    @on(OptionList.OptionSelected, "#model-tags")
    def _on_tag_selected(self, event: OptionList.OptionSelected) -> None:
        if not self._tags:
            return
        self._selected_ref = self._tags[event.option_index].ref
        self.query_one("#pull-status", Static).update(
            f"selected {self._selected_ref} — press Install"
        )

    @on(Button.Pressed, "#model-install")
    def _on_model_install(self) -> None:
        if self._selected_ref:
            self._enqueue_pull(self._selected_ref)

    def _enqueue_pull(self, ref: str) -> None:
        if ref in self._pull_queue:
            return
        self._pull_queue.append(ref)
        self._render_queue()
        if not self._pulling:
            self.run_worker(self._pull_worker(), group="pull", exclusive=True)

    def _render_queue(self) -> None:
        queued = self._pull_queue[1:] if self._pulling else self._pull_queue
        text = f"queued: {', '.join(queued)}" if queued else ""
        self.query_one("#pull-queue", Static).update(text)

    async def _pull_worker(self) -> None:
        self._pulling = True
        status = self.query_one("#pull-status", Static)
        bar = self.query_one("#pull-progress", ProgressBar)
        try:
            while self._pull_queue:
                ref = self._pull_queue[0]
                self._render_queue()
                bar.update(total=100, progress=0)
                try:
                    async for p in discovery.pull_model(self._config.llm.host, ref):
                        status.update(f"pulling {ref}: {p.status}")
                        bar.update(progress=p.percent)
                    status.update(f"pulled {ref} ✓")
                    self._ollamalog.write(f"pulled {ref}")
                except Exception as exc:  # noqa: BLE001 - network/server, surface and continue
                    status.update(f"pull of {ref} failed: {exc}")
                    self._ollamalog.write(f"pull of {ref} failed: {exc}")
                self._pull_queue.pop(0)
                self._render_queue()
                await self._refresh_installed()
                self.run_worker(self._populate_selects(), group="selects")
        finally:
            self._pulling = False

    @on(Button.Pressed, "#model-delete")
    async def _on_model_delete(self) -> None:
        opts = self.query_one("#installed-list", OptionList)
        idx = opts.highlighted
        if idx is None or not self._installed:
            return
        name = self._installed[idx].name
        if await discovery.delete_model(self._config.llm.host, name):
            self._ollamalog.write(f"deleted {name}")
        await self._refresh_installed()
        self.run_worker(self._populate_selects(), group="selects")

    async def _refresh_installed(self) -> None:
        self._installed = await discovery.ollama_models_info(self._config.llm.host)
        opts = self.query_one("#installed-list", OptionList)
        opts.clear_options()
        for m in self._installed:
            meta = " · ".join(p for p in (m.human_size if m.size else "", m.parameter_size) if p)
            opts.add_option(Option(f"{m.name}   {meta}".rstrip()))
        # Keep the browser's ✓ markers in sync with what's now installed.
        if self._search_results:
            self._render_search_results()
        if self._tags:
            self._render_tags()

    # ---- daemon control ------------------------------------------------------

    async def _start_daemon(self) -> None:
        await self.supervisor.start(self._overrides)
        self._set_state("running")
        self.run_worker(self._pump(), exclusive=True, group="pump")

    async def _pump(self) -> None:
        async for line in self.supervisor.lines():
            parsed = parse(line)
            self._applog.write(colorize_line(parsed.raw))
            if parsed.is_llm:
                self._llmlog.write(colorize_message(parsed.message or parsed.raw))
        # stdout EOF: the child exited.
        if self._state != "restarting":
            self._set_state("stopped")

    @on(Button.Pressed, "#btn-start")
    async def _on_start(self) -> None:
        if not self.supervisor.running:
            await self._start_daemon()

    @on(Button.Pressed, "#btn-stop")
    async def _on_stop(self) -> None:
        self._set_state("stopped")
        await self.supervisor.stop()

    @on(Button.Pressed, "#btn-restart")
    async def _on_restart(self) -> None:
        await self._restart()

    @on(Button.Pressed, "#btn-apply")
    async def _on_apply(self) -> None:
        self._collect_overrides()
        await self._restart()

    @on(Button.Pressed, "#btn-clear")
    def _on_clear(self) -> None:
        self._applog.clear()
        self._llmlog.clear()
        self._ollamalog.clear()

    async def _restart(self) -> None:
        self._set_state("restarting")
        await self.supervisor.restart(self._overrides)
        # Refresh the seed config so the status bar reflects applied overrides.
        self._config = discovery.current_config()
        self._set_state("running")
        self.run_worker(self._pump(), exclusive=True, group="pump")

    def _collect_overrides(self) -> None:
        form: dict[tuple[str, ...], str] = {}
        current: dict[tuple[str, ...], str] = {}
        for field in FIELDS:
            if field.kind == "multiselect":
                self._collect_multiselect_override(field)
                continue
            current[field.key] = discovery.current_value(self._config, field.key)
            widget = self.query_one(f"#{_field_id(field)}")
            value = widget.value
            if value in (None, Select.BLANK):
                continue
            form[field.key] = str(value)
        self._overrides.update(overrides_for(changed_fields(form, current)))

    def _collect_multiselect_override(self, field: Field) -> None:
        # wake.model_paths rides an env var as a JSON list (Config parses it back).
        sel = self.query_one(f"#{_field_id(field)}", SelectionList)
        selected = list(sel.selected)
        if set(selected) == set(self._config.wake.model_refs()):
            return  # unchanged from the effective config
        self._overrides[field.env] = json.dumps(selected)

    # ---- LLM server (Ollama) -------------------------------------------------

    async def _ensure_ollama(self) -> None:
        """Bring the LLM server up on launch and stream its output — no button press.

        Non-destructive: if a server is already responding we leave it alone (we
        can't capture an external process's output, and killing a healthy server
        would be surprising). Only start one when nothing answers."""
        if await discovery.ollama_health(self._config.llm.host):
            self._ollamalog.write("LLM server already running.")
            return
        self._ollamalog.write("Starting LLM server…")
        # Clear a stale/non-responding holder of the port so the child can bind.
        pid = await free_ollama_port(self._config.llm.host)
        if pid:
            self._ollamalog.write(f"Stopped stale ollama serve (pid {pid}).")
        await self.ollama.start()
        self.run_worker(self._pump_ollama(), exclusive=True, group="ollama-pump")
        self.run_worker(self._check_ollama_health(), group="health-now")

    @on(Button.Pressed, "#btn-ollama-restart")
    async def _on_ollama_restart(self) -> None:
        self._applog.write("Restarting LLM server… (see Ollama tab)")
        self._ollamalog.write("Restarting LLM server…")
        # A server we didn't spawn (a bare `ollama serve` from another shell) owns
        # the port; the supervisor can't SIGTERM a child it never started, so free
        # the port by pid first — otherwise `ollama serve` hits "address in use".
        if not self.ollama.running:
            pid = await free_ollama_port(self._config.llm.host)
            if pid:
                self._ollamalog.write(f"Stopped external ollama serve (pid {pid}).")
        await self.ollama.restart()
        # Stream the server's own output into the Ollama tab (so a failed start is
        # visible — the reason health was failing in the first place).
        self.run_worker(self._pump_ollama(), exclusive=True, group="ollama-pump")
        self.run_worker(self._check_ollama_health(), group="health-now")

    async def _pump_ollama(self) -> None:
        async for line in self.ollama.lines():
            self._ollamalog.write(colorize_line(line))

    async def _health_loop(self) -> None:
        while True:
            await self._check_ollama_health()
            await asyncio.sleep(HEALTH_POLL_SECONDS)

    async def _check_ollama_health(self) -> None:
        self._ollama_up = await discovery.ollama_health(self._config.llm.host)
        try:
            badge = "ollama: up" if self._ollama_up else "ollama: DOWN"
            self.query_one("#ollama-status", Static).update(badge)
        except Exception:  # noqa: BLE001 - widget not mounted yet
            pass
        self._refresh_status()

    # ---- config persistence --------------------------------------------------

    @on(Button.Pressed, "#config-save")
    async def _on_config_save(self) -> None:
        values: dict[tuple[str, ...], object] = {}
        for field in FIELDS:
            widget = self.query_one(f"#{_field_id(field)}")
            if field.kind == "multiselect":
                values[field.key] = coerce(field, list(widget.selected))
                continue
            value = widget.value
            if value in (None, Select.BLANK):
                continue
            values[field.key] = coerce(field, value)
        configfile.write_fields(configfile.CONFIG_FILE, values)
        self._applog.write(f"Saved {configfile.CONFIG_FILE} — restarting…")
        await self._restart()

    @on(Button.Pressed, "#config-reset")
    async def _on_config_reset(self) -> None:
        data = configfile.read(configfile.DEFAULT_CONFIG_FILE)
        if not data:
            self._applog.write(f"No {configfile.DEFAULT_CONFIG_FILE} found.")
            return
        defaults = discovery.config_from_dict(data)
        for field in FIELDS:
            if field.kind not in ("select", "multiselect"):
                self.query_one(f"#{_field_id(field)}", Input).value = discovery.current_value(
                    defaults, field.key
                )
        await self._populate_selects(defaults)
        self._applog.write(f"Reset fields to {configfile.DEFAULT_CONFIG_FILE} — Save to persist.")

    # ---- .env editor ---------------------------------------------------------

    @on(Button.Pressed, "#env-save")
    def _on_env_save(self) -> None:
        envfile.write(ENV_FILE, self.query_one("#envedit", TextArea).text)
        self._applog.write(f"Saved {ENV_FILE} — Restart to apply.")

    @on(Button.Pressed, "#env-add")
    def _on_env_add(self) -> None:
        editor = self.query_one("#envedit", TextArea)
        editor.text = envfile.add_missing(editor.text, envfile.read(ENV_EXAMPLE_FILE))

    @on(Button.Pressed, "#env-remove")
    def _on_env_remove(self) -> None:
        editor = self.query_one("#envedit", TextArea)
        editor.text = envfile.remove_extra(editor.text, envfile.read(ENV_EXAMPLE_FILE))

    @on(Button.Pressed, "#env-reload")
    def _on_env_reload(self) -> None:
        self.query_one("#envedit", TextArea).text = envfile.read(ENV_FILE)

    # ---- chat box ------------------------------------------------------------

    @on(Input.Submitted, "#chat")
    async def _on_chat(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        event.input.value = ""
        if not text:
            return
        self._llmlog.write(f"You (typed): {text}")
        await self.supervisor.send(f"TEXT {text}")

    # ---- volume / mute -------------------------------------------------------

    @on(Button.Pressed, ".volume-row Button")
    async def _on_volume_button(self, event: Button.Pressed) -> None:
        if event.button.id == "vol-mute":
            if self._muted:
                await self._apply_volume(self._last_volume, muted=False)
            else:
                if self._volume > 0.0:
                    self._last_volume = self._volume
                await self._apply_volume(0.0, muted=True)
            self.query_one("#vol-mute", Button).label = "Unmute" if self._muted else "Mute"
            return
        for _, value in VOLUME_PRESETS:
            if event.button.id == f"vol-{int(value * 100)}":
                await self._apply_volume(value, muted=False)
                self.query_one("#vol-mute", Button).label = "Mute"
                return

    async def _apply_volume(self, value: float, *, muted: bool) -> None:
        self._volume = value
        self._muted = muted
        # Live (no restart) via the control channel...
        await self.supervisor.send(f"SET audio.output_volume {value}")
        # ...and persist for the next (re)start via the env override + number field.
        self._overrides[VOLUME_ENV] = str(value)
        try:
            self.query_one(f"#{_field_id(_volume_field())}", Input).value = str(value)
        except Exception:  # noqa: BLE001 - widget may not exist in a custom layout
            pass
        self._refresh_status()

    # ---- status bar ----------------------------------------------------------

    def _set_state(self, state: str) -> None:
        self._state = state
        self._refresh_status()

    def _refresh_status(self) -> None:
        model = self._overrides.get("ASSISTANT_LLM__MODEL") or self._config.llm.model
        refs_override = self._overrides.get("ASSISTANT_WAKE__MODEL_PATHS")
        refs = json.loads(refs_override) if refs_override else None
        phrases = ", ".join(registry.phrases_for(refs or self._config.wake.model_refs())) or "(none)"
        vol = "MUTED" if self._muted else f"vol {self._volume:.2f}"
        ollama = "ollama up" if self._ollama_up else "ollama DOWN"
        # No square brackets: the status Static renders Rich markup, which would
        # swallow "[RUNNING]" as a tag.
        text = (
            f"{self._state.upper()}  |  model: {model}  |  {ollama}  "
            f"|  wake: {phrases}  |  {vol}"
        )
        try:
            self.query_one("#status", Static).update(text)
        except Exception:  # noqa: BLE001 - status not mounted yet
            pass

    async def on_unmount(self) -> None:
        await self.supervisor.stop()
        await self.ollama.stop()  # only stops it if the TUI started it


def _volume_field() -> Field:
    for field in FIELDS:
        if field.key == ("audio", "output_volume"):
            return field
    raise KeyError("output_volume field missing from schema")


def main() -> None:
    AssistantTUI().run()


if __name__ == "__main__":
    main()
