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
from tui.logparse import dedup_key, parse, parse_state
from tui.screens import (
    ConfigScreen,
    HomeScreen,
    InstalledScreen,
    LogsScreen,
    ModelDetailScreen,
    ModelsScreen,
    NowScreen,
    VoicesScreen,
)
from tui.screens.now import paused_banner
from tui.runlog import RunLogWriter, ollama_log_path
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


LLM_TIER_STYLE = {"up": "green", "degraded": "yellow", "down": "red"}


def _provider_label(name: str) -> str:
    """Short display name that fits the 40-col status line."""
    return "zen" if name == "opencode-zen" else name


def _ollama_in_chain(llm) -> bool:
    """True when the local Ollama server is the primary or the fallback."""
    return llm.provider == "ollama" or llm.fallback == "ollama"


def _derive_tier(primary_ok: bool, fallback_ok: bool | None) -> str:
    """up/degraded/down. ``fallback_ok`` is None when no fallback is configured
    (then there is no degraded state: it's up or down on the primary alone).
    Matches FallbackLLMProvider.health(): usable iff primary_ok or fallback_ok."""
    oks = [primary_ok] + ([] if fallback_ok is None else [fallback_ok])
    if all(oks):
        return "up"
    if any(oks):
        return "degraded"
    return "down"


def _llm_status_line(llm, primary_ok: bool, fallback_ok: bool | None, tier: str) -> str:
    """Provider-aware text, e.g. "zen ✓ · ollama ✓" / "zen ✗ · ollama ✓ (degraded)"."""
    parts = [f"{_provider_label(llm.provider)} {'✓' if primary_ok else '✗'}"]
    if llm.fallback:
        parts.append(f"{_provider_label(llm.fallback)} {'✓' if fallback_ok else '✗'}")
    line = " · ".join(parts)
    return f"{line} (degraded)" if tier == "degraded" else line


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
        self._llm_tier = "down"
        self._llm_status = "llm …"  # placeholder until the first probe
        self._volume = self._config.audio.output_volume
        self._muted = self._volume == 0.0
        self._last_volume = self._volume or 1.0
        # Models: registry browsing + a sequential pull queue.
        self._search_results: list[discovery.RegistryModel] = []
        self._installed: list[discovery.OllamaModel] = []
        self._voice_catalog: list[discovery.RegistryVoice] = []
        self._pull_queue: list[str] = []
        self._pulling = False
        self._last_query = _default_query(self._config.llm.model)
        # Log channels: writers exist once LogsScreen has mounted; until then
        # lines wait here (bounded like the widgets' backlog).
        self._writers: dict[str, CollapsingWriter] = {}
        # On-disk copy of the spawned Ollama server's output (the daemon writes
        # its own log files; only this channel would otherwise vanish on exit).
        self._ollama_log: RunLogWriter | None = None
        self._pending: dict[str, deque] = {
            name: deque(maxlen=MAX_LOG_LINES) for name in LOG_CHANNELS
        }

    # ---- lifecycle -----------------------------------------------------------

    async def on_mount(self) -> None:
        self._home = HomeScreen()
        self._now = NowScreen()
        self._logs_screen = LogsScreen()
        self._config_screen = ConfigScreen()
        self._models_screen = ModelsScreen()
        self._installed_screen = InstalledScreen()
        self._voices_screen = VoicesScreen()
        self.install_screen(self._home, name="home")
        self.install_screen(self._now, name="now")
        self.install_screen(self._logs_screen, name="logs")
        self.install_screen(self._config_screen, name="config")
        self.install_screen(self._models_screen, name="models")
        self.install_screen(self._installed_screen, name="installed")
        self.install_screen(self._voices_screen, name="voices")
        # Now is the default face; Home sits under it as the ◀ settings/status hub.
        await self.push_screen("home")
        await self.push_screen("now")
        self._refresh_status()
        self.run_worker(self._startup(), group="startup")
        self.run_worker(self._health_loop(), group="health")

    async def _startup(self) -> None:
        await self._start_daemon()
        await self._ensure_ollama()

    async def on_unmount(self) -> None:
        await self.supervisor.stop()
        await self.ollama.stop()  # only stops it if the TUI started it
        if self._ollama_log is not None:
            self._ollama_log.close()

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
            payload = parse_state(line)
            if payload is not None:
                self._on_state(payload)
                continue
            parsed = parse(line)
            key = dedup_key(parsed)
            self._log("app", colorize_line(parsed.raw), key)
            if parsed.is_llm:
                self._log("llm", colorize_message(parsed.message or parsed.raw), key)
        # stdout EOF: the child exited.
        if self._state != "restarting":
            self._set_state("stopped")

    def _on_state(self, payload: dict) -> None:
        """Drive the Now screen from a daemon state-feed line."""
        if not self._now.is_attached:  # not mounted yet — nothing to update
            return
        state = payload.get("state")
        if state:
            self._now.set_state(state)
        if "transcript" in payload:
            self._now.set_transcript(payload["transcript"])
        if "text" in payload:
            self._now.set_reply(payload["text"])
        if payload.get("message") and state in ("no_speech", "error"):
            self._now.set_banner(payload["message"])
        if state == "paused":
            self._now.set_banner(paused_banner(payload.get("remaining")))
        if "level" in payload:
            self._now.set_level(payload["level"])

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
        if not _ollama_in_chain(self._config.llm):
            return
        if await discovery.ollama_health(self._config.llm.host):
            self._log("ollama", "LLM server already running.")
            return
        self._log("ollama", "Starting LLM server…")
        # Clear a stale/non-responding holder of the port so the child can bind.
        pid = await free_ollama_port(self._config.llm.host)
        if pid:
            self._log("ollama", f"Stopped stale ollama serve (pid {pid}).")
        await self.ollama.start()
        self._open_ollama_log()
        self.run_worker(self._pump_ollama(), exclusive=True, group="ollama-pump")
        self.run_worker(self._check_llm_health(), group="health-now")

    async def _on_ollama_restart(self) -> None:
        if not _ollama_in_chain(self._config.llm):
            return
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
        self._open_ollama_log()
        self.run_worker(self._pump_ollama(), exclusive=True, group="ollama-pump")
        self.run_worker(self._check_llm_health(), group="health-now")

    def _open_ollama_log(self) -> None:
        """Start a fresh per-run file for the server we just spawned."""
        if self._ollama_log is not None:
            self._ollama_log.close()
            self._ollama_log = None
        if self._config.logging.file_enabled:
            self._ollama_log = RunLogWriter(
                ollama_log_path(self._config.logging.dir),
                self._config.logging.rotate_max_bytes,
            )

    async def _pump_ollama(self) -> None:
        async for line in self.ollama.lines():
            if self._ollama_log is not None:
                try:
                    self._ollama_log.write(line)
                except OSError as exc:
                    log.warning("Ollama log write failed (%s); disabling file copy", exc)
                    self._ollama_log = None
            self._log("ollama", colorize_line(line), line)

    async def _health_loop(self) -> None:
        while True:
            await self._check_llm_health()
            await asyncio.sleep(HEALTH_POLL_SECONDS)

    async def _probe_provider(self, name: str) -> bool:
        llm = self._config.llm
        if name == "opencode-zen":
            return await discovery.zen_health(llm.base_url, llm.api_key)
        return await discovery.ollama_health(llm.host)

    async def _check_llm_health(self) -> None:
        llm = self._config.llm
        primary_ok = await self._probe_provider(llm.provider)
        fallback_ok = await self._probe_provider(llm.fallback) if llm.fallback else None
        self._llm_tier = _derive_tier(primary_ok, fallback_ok)
        self._llm_status = _llm_status_line(llm, primary_ok, fallback_ok, self._llm_tier)
        self._refresh_status()

    # ---- config editing --------------------------------------------------------

    async def _select_options(self, field: Field, current: str = "") -> list[tuple[str, str]]:
        """Resolve a field's options provider into (label, value) pairs.

        Providers share the ``(host=..., **_)`` signature; the LLM-identity
        providers also read ``provider``/``base_url``/``api_key``/``fallback``
        off the same ``**_`` (backward-compatible — other providers ignore them)."""
        llm = self._config.llm
        try:
            result = field.options(
                host=llm.host,
                provider=llm.provider,
                base_url=llm.base_url,
                api_key=getattr(llm, f"{llm.provider}_api_key", ""),
                fallback=llm.fallback,
            ) if field.options else []
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
        wake_field = next(f for f in FIELDS if f.key == ("wake", "model_paths"))
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
        try:
            detail = self._config_screen.query_one("#model-detail", Static)
        except Exception:  # noqa: BLE001 - config screen not visited yet
            return
        # Zen models live server-side; /v1/models returns only ids (no
        # sizes/params/quant), so the Ollama-rich detail panel doesn't apply.
        if self._config.llm.provider == "opencode-zen":
            detail.update(f"{name}: server-side model · details unavailable")
            return
        host = self._config.llm.host
        info = await discovery.ollama_model_detail(host, name)
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

    async def _on_model_picked(self, value: str) -> None:
        """Picking an LLM model makes it the new default immediately: persist to
        config.yaml (and drop any env override that would shadow it), then restart."""
        if value == self._config.llm.model and "ASSISTANT_LLM__MODEL" not in self._overrides:
            return
        configfile.write_fields(configfile.CONFIG_FILE, {("llm", "model"): value})
        self._overrides.pop("ASSISTANT_LLM__MODEL", None)
        self._log("app", f"LLM model set to {value} — saved as default, restarting…")
        await self._restart()

    async def _on_llm_identity_picked(self, field: Field, value: str) -> None:
        """Persist an LLM-identity pick (provider/fallback/fallback_model) to
        config.yaml as the new default, drop any env override that would shadow
        it, and restart so the daemon rebuilds the provider chain. Same shape as
        _on_model_picked, generalized over the field."""
        current = discovery.current_value(self._config, field.key)
        if value == current and field.env not in self._overrides:
            return
        configfile.write_fields(configfile.CONFIG_FILE, {field.key: value})
        self._overrides.pop(field.env, None)
        self._log("app", f"{field.label} set to {value!r} — saved as default, restarting…")
        await self._restart()

    async def _on_voice_picked(self, value: str) -> None:
        """Picking a voice persists it and restarts: the daemon reloads Piper at the
        new voice's sample rate (a bare rate/ack tweak is live, a model swap isn't)."""
        if value == self._config.tts.model_path and "ASSISTANT_TTS__MODEL_PATH" not in self._overrides:
            return
        configfile.write_fields(configfile.CONFIG_FILE, {("tts", "model_path"): value})
        self._overrides.pop("ASSISTANT_TTS__MODEL_PATH", None)
        self._log("app", f"Voice set to {os.path.basename(value)} — saved, restarting…")
        await self._restart()

    async def _on_test_voice(self) -> None:
        """Speak a sample line through the running daemon at the currently-selected
        rate — a live preview over the control channel, no restart."""
        try:
            rate = self._config_screen.query_one("#field-tts_length_scale", Stepper).value_str
        except Exception:  # noqa: BLE001 - config screen not mounted yet
            rate = ""
        sample = "hmm? Testing the voice. The weather today is sunny and mild."
        await self.supervisor.send(f"SAY {rate}|{sample}" if rate else f"SAY {sample}")
        self._log("app", "Testing voice…")

    async def _load_voice_catalog(self) -> None:
        self._voice_catalog = await discovery.piper_voice_catalog()
        if self._voices_screen.is_attached:
            self._voices_screen.render_catalog(self._voice_catalog)

    async def _do_voice_download(self, voice: discovery.RegistryVoice) -> None:
        try:
            async for p in discovery.download_voice(voice):
                self._voices_screen.set_download_status(p.status, p.percent)
        except Exception as exc:  # noqa: BLE001 - a download failure must not crash the TUI
            self._voices_screen.set_download_status(f"download failed: {exc}", None)
            self._log("app", f"Voice download failed: {exc}")
            return
        self._log("app", f"Downloaded voice {voice.key} — now selectable in Config.")
        await self._load_voice_catalog()  # refresh the ✓ installed marks

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
        # A multiselect rides an env var as a JSON list (Config parses it back).
        for field in FIELDS:
            if field.kind != "multiselect":
                continue
            selected = self._config_screen.selected_multiselect(field)
            if field.key == ("wake", "model_paths"):
                current = self._config.wake.model_refs()
            else:
                current = discovery.current_value_list(self._config, field.key)
            if set(selected) != set(current):
                self._overrides[field.env] = json.dumps(selected)

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
        text.append("● ", style=LLM_TIER_STYLE[self._llm_tier])
        text.append(self._llm_status + "\n")
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
            self._home.query_one("#row-ollama-restart").display = _ollama_in_chain(
                self._config.llm
            )
        except Exception:  # noqa: BLE001 - home not mounted yet
            pass
        daemon_up = self._state == "running"
        for screen in (self._now, self._config_screen, self._models_screen, self._installed_screen):
            if screen.is_attached:
                screen.query_one(NavBar).set_dots(daemon_up, self._llm_tier)


def main() -> None:
    AssistantTUI().run()


if __name__ == "__main__":
    main()
