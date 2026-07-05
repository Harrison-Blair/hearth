"""Textual monitor TUI for the assistant daemon.

Supervises ``python -m assistant.app`` as a child, streams its logs into the
Logs screen's App/LLM/Ollama channels, edits config via ``ASSISTANT_*`` env
overrides (applied on restart), and drives the live daemon over its stdin
control channel (instant mute/volume; a desktop-only chat modal that mimics
transcribed speech). Laid out for a 3.5" 320x480 portrait touchscreen
(≈40x30 cells) — one focused screen per job, full-width tappable buttons.

The app is the controller: it owns the supervisors, log pumps, health poll,
pull queue, and volume state. Screens (``tui/screens/``) are thin views that
call back into the app. Screens are installed once and stay mounted after
their first visit, so log writes land while they're covered; writes before the
Logs screen's first visit are buffered and drained on its mount.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import os
import re
from collections import deque

from rich.text import Text
from textual import on
from textual.app import App
from textual.events import TextSelected
from textual.widgets import Button, Static

from assistant.wake import registry
from tui import configfile, discovery
from tui.collapse import CollapsingWriter
from tui.config_schema import FIELDS, Field, changed_fields, overrides_for
from tui.logcolor import colorize_line, colorize_message
from tui.logparse import dedup_key, parse
from tui.screens import (
    ConfigScreen,
    HomeScreen,
    InstalledScreen,
    LogsScreen,
    ModelDetailScreen,
    ModelsScreen,
)
from tui.supervisor import DaemonSupervisor, free_ollama_port
from tui.widgets import NavBar, ScreenWidthRichLog, Stepper  # noqa: F401 - re-exported

log = logging.getLogger(__name__)

VOLUME_ENV = "ASSISTANT_AUDIO__OUTPUT_VOLUME"
MAX_LOG_LINES = 1000
HEALTH_POLL_SECONDS = 5.0
LOG_CHANNELS = ("app", "llm", "ollama")


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


class AssistantTUI(App):
    CSS = """
    Button { min-width: 0; padding: 0 1; height: 3; }
    RichLog { background: $surface; }
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
        # Models: registry browsing + a sequential pull queue.
        self._search_results: list[discovery.RegistryModel] = []
        self._installed: list[discovery.OllamaModel] = []
        self._pull_queue: list[str] = []
        self._pulling = False
        self._last_query = _default_query(self._config.llm.model)
        # Log channels: writers exist once LogsScreen has mounted; until then
        # lines wait here (bounded like the widgets' backlog).
        self._writers: dict[str, CollapsingWriter] = {}
        self._pending: dict[str, deque] = {
            name: deque(maxlen=MAX_LOG_LINES) for name in LOG_CHANNELS
        }

    # ---- lifecycle -----------------------------------------------------------

    async def on_mount(self) -> None:
        self._home = HomeScreen()
        self._logs_screen = LogsScreen()
        self._config_screen = ConfigScreen()
        self._models_screen = ModelsScreen()
        self._installed_screen = InstalledScreen()
        self.install_screen(self._home, name="home")
        self.install_screen(self._logs_screen, name="logs")
        self.install_screen(self._config_screen, name="config")
        self.install_screen(self._models_screen, name="models")
        self.install_screen(self._installed_screen, name="installed")
        await self.push_screen("home")
        self._refresh_status()
        self.run_worker(self._startup(), group="startup")
        self.run_worker(self._health_loop(), group="health")

    async def _startup(self) -> None:
        await self._start_daemon()
        await self._ensure_ollama()

    async def on_unmount(self) -> None:
        await self.supervisor.stop()
        await self.ollama.stop()  # only stops it if the TUI started it

    @on(TextSelected)
    async def _on_text_selected(self) -> None:
        text = self.screen.get_selected_text()
        if text:
            self.copy_to_clipboard(text)

    # ---- log channels ----------------------------------------------------------

    def _attach_logs(self, screen: LogsScreen) -> None:
        """LogsScreen mounted: wire its widgets up and drain the buffered lines."""
        for name in LOG_CHANNELS:
            self._writers[name] = CollapsingWriter(screen.log_widget(name))
            pending = self._pending[name]
            while pending:
                text, key = pending.popleft()
                self._writers[name].write(text, key)

    def _log(self, channel: str, content: str | Text, key: str | None = None) -> None:
        text = content if isinstance(content, Text) else Text(str(content))
        key = key if key is not None else text.plain
        writer = self._writers.get(channel)
        if writer is not None:
            writer.write(text, key)
        else:
            self._pending[channel].append((text, key))

    def _reset_writer(self, channel: str) -> None:
        writer = self._writers.get(channel)
        if writer is not None:
            writer.reset()  # its tail strip count is stale after a re-wrap/clear

    def _clear_logs(self) -> None:
        for name in LOG_CHANNELS:
            if name in self._writers:
                self._logs_screen.log_widget(name).clear()
            self._pending[name].clear()
            self._reset_writer(name)

    async def _send_text(self, text: str) -> None:
        """Inject a typed utterance as if it were transcribed speech (desktop chat)."""
        self._log("llm", f"You (typed): {text}")
        await self.supervisor.send(f"TEXT {text}")

    # ---- daemon control ------------------------------------------------------

    async def _start_daemon(self) -> None:
        await self.supervisor.start(self._overrides)
        self._set_state("running")
        self.run_worker(self._pump(), exclusive=True, group="pump")

    async def _pump(self) -> None:
        async for line in self.supervisor.lines():
            parsed = parse(line)
            key = dedup_key(parsed)
            self._log("app", colorize_line(parsed.raw), key)
            if parsed.is_llm:
                self._log("llm", colorize_message(parsed.message or parsed.raw), key)
        # stdout EOF: the child exited.
        if self._state != "restarting":
            self._set_state("stopped")

    async def _on_start(self) -> None:
        if not self.supervisor.running:
            await self._start_daemon()

    async def _on_stop(self) -> None:
        self._set_state("stopped")
        await self.supervisor.stop()

    async def _restart(self) -> None:
        self._set_state("restarting")
        await self.supervisor.restart(self._overrides)
        # Refresh the seed config so the status panel reflects applied overrides.
        self._config = discovery.current_config()
        self._set_state("running")
        self.run_worker(self._pump(), exclusive=True, group="pump")

    # ---- LLM server (Ollama) -------------------------------------------------

    async def _ensure_ollama(self) -> None:
        """Bring the LLM server up on launch and stream its output — no button press.

        Non-destructive: if a server is already responding we leave it alone (we
        can't capture an external process's output, and killing a healthy server
        would be surprising). Only start one when nothing answers."""
        if await discovery.ollama_health(self._config.llm.host):
            self._log("ollama", "LLM server already running.")
            return
        self._log("ollama", "Starting LLM server…")
        # Clear a stale/non-responding holder of the port so the child can bind.
        pid = await free_ollama_port(self._config.llm.host)
        if pid:
            self._log("ollama", f"Stopped stale ollama serve (pid {pid}).")
        await self.ollama.start()
        self.run_worker(self._pump_ollama(), exclusive=True, group="ollama-pump")
        self.run_worker(self._check_ollama_health(), group="health-now")

    async def _on_ollama_restart(self) -> None:
        self._log("app", "Restarting LLM server… (see Ollama channel in Logs)")
        self._log("ollama", "Restarting LLM server…")
        # A server we didn't spawn (a bare `ollama serve` from another shell) owns
        # the port; the supervisor can't SIGTERM a child it never started, so free
        # the port by pid first — otherwise `ollama serve` hits "address in use".
        if not self.ollama.running:
            pid = await free_ollama_port(self._config.llm.host)
            if pid:
                self._log("ollama", f"Stopped external ollama serve (pid {pid}).")
        await self.ollama.restart()
        # Stream the server's own output into the Ollama channel (so a failed start
        # is visible — the reason health was failing in the first place).
        self.run_worker(self._pump_ollama(), exclusive=True, group="ollama-pump")
        self.run_worker(self._check_ollama_health(), group="health-now")

    async def _pump_ollama(self) -> None:
        async for line in self.ollama.lines():
            self._log("ollama", colorize_line(line), line)

    async def _health_loop(self) -> None:
        while True:
            await self._check_ollama_health()
            await asyncio.sleep(HEALTH_POLL_SECONDS)

    async def _check_ollama_health(self) -> None:
        self._ollama_up = await discovery.ollama_health(self._config.llm.host)
        self._refresh_status()

    # ---- config editing --------------------------------------------------------

    async def _select_options(self, field: Field, current: str = "") -> list[tuple[str, str]]:
        """Resolve a field's options provider into (label, value) pairs."""
        try:
            result = field.options(host=self._config.llm.host) if field.options else []
            if inspect.isawaitable(result):
                result = await result
        except Exception as exc:  # noqa: BLE001 - discovery is best-effort
            log.warning("option discovery for %s failed: %s", field.key, exc)
            result = []
        pairs = [_as_option(item) for item in result]
        if current and current not in [value for _, value in pairs]:
            pairs.insert(0, (current, current))
        return pairs

    async def _refresh_wake_options(self, cfg=None) -> None:
        wake_field = next(f for f in FIELDS if f.kind == "multiselect")
        options = await self._select_options(wake_field)
        self._config_screen.populate_wake_models(cfg or self._config, options)

    def _clean_smoke_models(self) -> None:
        removed = discovery.clean_smoke_models()
        if removed:
            self._log(
                "app",
                f"Removed {len(removed)} smoke-test model(s): "
                + ", ".join(os.path.basename(p) for p in removed),
            )
        else:
            self._log("app", "No smoke-test models to remove.")
        self.run_worker(self._refresh_wake_options(), group="wake-options")

    async def _show_model_detail(self, name: str) -> None:
        host = self._config.llm.host
        info = await discovery.ollama_model_detail(host, name)
        try:
            detail = self._config_screen.query_one("#model-detail", Static)
        except Exception:  # noqa: BLE001 - config screen not visited yet
            return
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

    async def _on_config_save(self, values: dict[tuple[str, ...], object]) -> None:
        configfile.write_fields(configfile.CONFIG_FILE, values)
        self._log("app", f"Saved {configfile.CONFIG_FILE} — restarting…")
        await self._restart()

    async def _on_config_apply(self, form: dict[tuple[str, ...], str]) -> None:
        current = {
            field.key: discovery.current_value(self._config, field.key)
            for field in FIELDS
            if field.kind != "multiselect"
        }
        self._overrides.update(overrides_for(changed_fields(form, current)))
        self._collect_multiselect_override()
        await self._restart()

    def _collect_multiselect_override(self) -> None:
        # wake.model_paths rides an env var as a JSON list (Config parses it back).
        wake_field = next(f for f in FIELDS if f.kind == "multiselect")
        selected = self._config_screen.selected_wake_models()
        if set(selected) == set(self._config.wake.model_refs()):
            return  # unchanged from the effective config
        self._overrides[wake_field.env] = json.dumps(selected)

    async def _on_config_reset(self) -> None:
        data = configfile.read(configfile.DEFAULT_CONFIG_FILE)
        if not data:
            self._log("app", f"No {configfile.DEFAULT_CONFIG_FILE} found.")
            return
        defaults = discovery.config_from_dict(data)
        self._config_screen.set_from_config(defaults)
        await self._refresh_wake_options(cfg=defaults)
        self._log("app", f"Reset fields to {configfile.DEFAULT_CONFIG_FILE} — Save to persist.")

    # ---- models (registry search / pull queue / installed) ---------------------

    async def _do_search(self, query: str, *, refresh: bool = False) -> None:
        self._search_results = await discovery.search_registry(query, refresh=refresh)
        self._models_screen.render_results(self._search_results, self._installed_names())

    def _installed_names(self) -> set[str]:
        return {m.name for m in self._installed}

    def _open_model_detail(self, model: discovery.RegistryModel) -> None:
        async def _load_and_push() -> None:
            tags = await discovery.registry_tags(model.name)
            self.push_screen(ModelDetailScreen(model, tags))

        self.run_worker(_load_and_push(), group="tags", exclusive=True)

    def _enqueue_pull(self, ref: str) -> None:
        if ref in self._pull_queue:
            return
        self._pull_queue.append(ref)
        self._render_pull(f"queued {ref}", None)
        if not self._pulling:
            self.run_worker(self._pull_worker(), group="pull", exclusive=True)

    def _render_pull(self, status: str, percent: float | None) -> None:
        queued = self._pull_queue[1:] if self._pulling else self._pull_queue
        if self._models_screen.is_attached:
            self._models_screen.set_pull_status(status, percent, queued)

    async def _pull_worker(self) -> None:
        self._pulling = True
        try:
            while self._pull_queue:
                ref = self._pull_queue[0]
                self._render_pull(f"pulling {ref}…", 0)
                try:
                    async for p in discovery.pull_model(self._config.llm.host, ref):
                        self._render_pull(f"pulling {ref}: {p.status}", p.percent)
                    self._render_pull(f"pulled {ref} ✓", 100)
                    self._log("ollama", f"pulled {ref}")
                except Exception as exc:  # noqa: BLE001 - network/server, surface and continue
                    self._render_pull(f"pull of {ref} failed: {exc}", None)
                    self._log("ollama", f"pull of {ref} failed: {exc}")
                self._pull_queue.pop(0)
                await self._refresh_installed()
        finally:
            self._pulling = False
            self._render_pull("", None)

    async def _refresh_installed(self) -> None:
        self._installed = await discovery.ollama_models_info(self._config.llm.host)
        if self._installed_screen.is_attached:
            self._installed_screen.render_installed(self._installed)
        # Keep the browser's ✓ markers in sync with what's now installed.
        if self._search_results and self._models_screen.is_attached:
            self._models_screen.render_results(self._search_results, self._installed_names())

    async def _delete_model(self, name: str) -> None:
        if await discovery.delete_model(self._config.llm.host, name):
            self._log("ollama", f"deleted {name}")
        await self._refresh_installed()

    # ---- volume / mute -------------------------------------------------------

    async def _on_mute(self) -> None:
        if self._muted:
            await self._apply_volume(self._last_volume, muted=False)
        else:
            if self._volume > 0.0:
                self._last_volume = self._volume
            await self._apply_volume(0.0, muted=True)

    async def _nudge_volume(self, delta: float) -> None:
        value = round(max(0.0, min(1.0, self._volume + delta)), 2)
        await self._apply_volume(value, muted=value == 0)

    async def _apply_volume(self, value: float, *, muted: bool) -> None:
        self._volume = value
        self._muted = muted
        # Live (no restart) via the control channel...
        await self.supervisor.send(f"SET audio.output_volume {value}")
        # ...and persist for the next (re)start via the env override.
        self._overrides[VOLUME_ENV] = str(value)
        if self._config_screen.is_attached:
            self._config_screen.set_volume(value)
        self._refresh_status()

    # ---- status ---------------------------------------------------------------

    def _set_state(self, state: str) -> None:
        self._state = state
        self._refresh_status()

    def _status_text(self) -> Text:
        model = self._overrides.get("ASSISTANT_LLM__MODEL") or self._config.llm.model
        refs_override = self._overrides.get("ASSISTANT_WAKE__MODEL_PATHS")
        refs = json.loads(refs_override) if refs_override else None
        phrases = ", ".join(registry.phrases_for(refs or self._config.wake.model_refs())) or "(none)"
        state_style = {"running": "green", "restarting": "yellow"}.get(self._state, "red")
        text = Text()
        text.append("● ", style=state_style)
        text.append(f"daemon {self._state.upper()}\n")
        text.append("● ", style="green" if self._ollama_up else "red")
        text.append("ollama up\n" if self._ollama_up else "ollama DOWN\n")
        text.append(f"model: {model}\n")
        text.append(f"wake: {phrases}\n")
        text.append("MUTED" if self._muted else f"vol {int(round(self._volume * 100))}%")
        return text

    def _refresh_status(self) -> None:
        try:
            self._home.query_one("#home-status", Static).update(self._status_text())
            self._home.query_one("#btn-toggle-daemon", Button).label = (
                "Stop" if self._state == "running" else "Start"
            )
            self._home.query_one("#vol-value", Static).update(
                "MUTED" if self._muted else f"{int(round(self._volume * 100))}%"
            )
            self._home.query_one("#vol-mute", Button).label = (
                "Unmute" if self._muted else "Mute"
            )
        except Exception:  # noqa: BLE001 - home not mounted yet
            pass
        daemon_up = self._state == "running"
        for screen in (self._config_screen, self._models_screen, self._installed_screen):
            if screen.is_attached:
                screen.query_one(NavBar).set_dots(daemon_up, self._ollama_up)


def main() -> None:
    AssistantTUI().run()


if __name__ == "__main__":
    main()
