import pytest
from textual.widgets import Static

from assistant.core.config import Config, LlmConfig
from tui import discovery
from tui.app import AssistantTUI
from tui.supervisor import DaemonSupervisor


@pytest.fixture(autouse=True)
def _hermetic_config(monkeypatch):
    # Seed the app from typed defaults, never the developer's live config.yaml
    # (full section dumps: init dicts deep-merge with yaml, so every key must win).
    monkeypatch.setattr(
        discovery,
        "current_config",
        lambda: Config(**{n: f.default.model_dump() for n, f in Config.model_fields.items()}),
    )


def test_serve_cmd_default():
    assert LlmConfig().serve_cmd == ["ollama", "serve"]


class FakeSupervisor(DaemonSupervisor):
    def __init__(self, lines=()):
        super().__init__()
        self.restarts = 0
        self.stops = 0
        self._lines = list(lines)
        self._running = False

    @property
    def running(self):
        return self._running

    async def start(self, overrides=None):
        self._running = True

    async def stop(self, timeout=5.0):
        self.stops += 1
        self._running = False

    async def restart(self, overrides=None):
        self.restarts += 1
        self._running = True

    async def send(self, line):
        pass

    async def lines(self):
        for line in self._lines:
            yield line


def _fake_health(value):
    async def _health(host=discovery.DEFAULT_HOST, **_):
        return value

    return _health


async def _fake_free_none(host, timeout=5.0):
    return None


async def _channel_text(app, pilot, channel):
    """Show the channel (hidden RichLogs defer rendering until sized) and read it."""
    app._logs_screen.show_channel(channel)
    await pilot.pause()
    widget = app._logs_screen.log_widget(channel)
    # Join without separators: at 40 cols a logical line wraps across strips.
    return "".join(seg.text for strip in widget.lines for seg in strip)


async def test_restart_llm_restarts_server_and_streams_output(monkeypatch):
    monkeypatch.setattr(discovery, "ollama_health", _fake_health(True))
    ollama = FakeSupervisor(lines=["server starting", "listening on 11434"])
    # The TUI owns this server (started it), so restart is safe — no bind clash.
    ollama._running = True
    app = AssistantTUI(supervisor=FakeSupervisor(), ollama=ollama)
    async with app.run_test(size=(40, 30)) as pilot:
        await pilot.pause()
        await app._on_ollama_restart()
        await pilot.pause()
        assert ollama.restarts == 1
        # Show the Logs screen so the buffered lines render into the widgets.
        app.push_screen("logs")
        await pilot.pause()
        # The App channel gets only the action notice, pointing at the Ollama channel.
        assert "see Ollama channel" in await _channel_text(app, pilot, "app")
        # The two streamed server lines (+ the "Restarting…" notice) land in the
        # dedicated Ollama channel.
        ollama_text = await _channel_text(app, pilot, "ollama")
        assert "server starting" in ollama_text and "listening on 11434" in ollama_text


async def test_restart_llm_adopts_external_server(monkeypatch):
    # Server already listening but the TUI never started it (running=False) => a
    # bare `ollama serve` from another shell. Restart must free the port by pid
    # (so the fresh child can bind), then start it.
    monkeypatch.setattr(discovery, "ollama_health", _fake_health(True))
    freed = {}

    async def _fake_free(host, timeout=5.0):
        freed["host"] = host
        return 4242

    monkeypatch.setattr("tui.app.free_ollama_port", _fake_free)
    ollama = FakeSupervisor()  # _running defaults to False
    app = AssistantTUI(supervisor=FakeSupervisor(), ollama=ollama)
    async with app.run_test(size=(40, 30)) as pilot:
        await pilot.pause()
        await app._on_ollama_restart()
        await pilot.pause()
        assert freed["host"] == app._config.llm.host
        assert ollama.restarts == 1
        app.push_screen("logs")
        await pilot.pause()
        text = await _channel_text(app, pilot, "ollama")
        assert "Stopped external ollama serve (pid 4242)" in text


async def test_ollama_channel_one_tap_from_logs(monkeypatch):
    # The locked intent of the old "tab-ollama sits after tab-logs" test: the
    # Ollama output is one tap away once you're looking at logs.
    monkeypatch.setattr(discovery, "ollama_health", _fake_health(True))
    app = AssistantTUI(supervisor=FakeSupervisor(), ollama=FakeSupervisor())
    async with app.run_test(size=(40, 30)) as pilot:
        await pilot.pause()
        app.push_screen("logs")
        await pilot.pause()
        await pilot.click("#chan-ollama")
        await pilot.pause()
        assert app._logs_screen.active_channel == "ollama"
        ollama_log = app._logs_screen.log_widget("ollama")
        assert ollama_log.display
        assert not app._logs_screen.log_widget("app").display
        # Health stubbed up, so the launch auto-start notes the running server.
        text = "".join(seg.text for strip in ollama_log.lines for seg in strip)
        assert "LLM server already running" in text


async def test_health_badge_reflects_up(monkeypatch):
    monkeypatch.setattr(discovery, "ollama_health", _fake_health(True))
    app = AssistantTUI(supervisor=FakeSupervisor(), ollama=FakeSupervisor())
    async with app.run_test(size=(40, 30)) as pilot:
        await pilot.pause()
        status = str(app._home.query_one("#home-status", Static).render())
        assert "ollama ✓" in status


async def test_health_badge_reflects_down(monkeypatch):
    monkeypatch.setattr(discovery, "ollama_health", _fake_health(False))
    monkeypatch.setattr("tui.app.free_ollama_port", _fake_free_none)
    app = AssistantTUI(supervisor=FakeSupervisor(), ollama=FakeSupervisor())
    async with app.run_test(size=(40, 30)) as pilot:
        await pilot.pause()
        status = str(app._home.query_one("#home-status", Static).render())
        assert "ollama ✗" in status


async def test_ollama_autostarts_when_down(monkeypatch):
    # No server answering on launch => the TUI starts one and streams its output,
    # with no button press.
    monkeypatch.setattr(discovery, "ollama_health", _fake_health(False))
    monkeypatch.setattr("tui.app.free_ollama_port", _fake_free_none)
    ollama = FakeSupervisor(lines=["server starting", "listening on 11434"])
    app = AssistantTUI(supervisor=FakeSupervisor(), ollama=ollama)
    async with app.run_test(size=(40, 30)) as pilot:
        await pilot.pause()
        assert ollama.running
        app.push_screen("logs")
        await pilot.pause()
        ollama_text = await _channel_text(app, pilot, "ollama")
        assert "Starting LLM server…" in ollama_text
        assert "server starting" in ollama_text and "listening on 11434" in ollama_text


async def test_navbar_dots_reflect_daemon_and_ollama(monkeypatch):
    monkeypatch.setattr(discovery, "ollama_health", _fake_health(True))
    app = AssistantTUI(supervisor=FakeSupervisor(), ollama=FakeSupervisor())
    async with app.run_test(size=(40, 30)) as pilot:
        await pilot.pause()
        app.push_screen("config")
        await pilot.pause()
        from tui.widgets import NavBar

        dots = app._config_screen.query_one(NavBar).query_one(".nav-dots", Static).render()
        styles = [str(s.style) for s in getattr(dots, "spans", [])]
        # The fake daemon's stdout EOFs immediately => daemon dot red; ollama green.
        assert len(styles) == 2
        assert "red" in styles[0] and "green" in styles[1]
