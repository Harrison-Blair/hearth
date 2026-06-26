from textual.widgets import RichLog, Static, TabbedContent, TabPane

from assistant.core.config import LlmConfig
from assistant.tui import discovery
from assistant.tui.app import AssistantTUI
from assistant.tui.supervisor import DaemonSupervisor


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


async def test_restart_llm_restarts_server_and_streams_output(monkeypatch):
    monkeypatch.setattr(discovery, "ollama_health", _fake_health(True))
    ollama = FakeSupervisor(lines=["server starting", "listening on 11434"])
    # The TUI owns this server (started it), so restart is safe — no bind clash.
    ollama._running = True
    app = AssistantTUI(supervisor=FakeSupervisor(), ollama=ollama)
    async with app.run_test() as pilot:
        await pilot.pause()
        await app._on_ollama_restart()
        await pilot.pause()
        assert ollama.restarts == 1
        # The Logs tab gets only the action notice, pointing at the Ollama tab.
        applog_text = "\n".join(str(line) for line in app.query_one("#applog", RichLog).lines)
        assert "see Ollama tab" in applog_text
        # The two streamed server lines (+ the "Restarting…" notice) land in the
        # dedicated Ollama tab. RichLog only renders rows once the pane is sized.
        app.query_one(TabbedContent).active = "tab-ollama"
        await pilot.pause()
        ollama_text = "\n".join(str(line) for line in app.query_one("#ollamalog", RichLog).lines)
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

    monkeypatch.setattr("assistant.tui.app.free_ollama_port", _fake_free)
    ollama = FakeSupervisor()  # _running defaults to False
    app = AssistantTUI(supervisor=FakeSupervisor(), ollama=ollama)
    async with app.run_test() as pilot:
        await pilot.pause()
        await app._on_ollama_restart()
        await pilot.pause()
        assert freed["host"] == app._config.llm.host
        assert ollama.restarts == 1
        app.query_one(TabbedContent).active = "tab-ollama"
        await pilot.pause()
        ollama_text = "\n".join(str(line) for line in app.query_one("#ollamalog", RichLog).lines)
        assert "Stopped external ollama serve (pid 4242)" in ollama_text


async def test_ollama_tab_sits_after_logs(monkeypatch):
    monkeypatch.setattr(discovery, "ollama_health", _fake_health(True))
    app = AssistantTUI(supervisor=FakeSupervisor(), ollama=FakeSupervisor())
    async with app.run_test() as pilot:
        await pilot.pause()
        # Tab order: Logs then Ollama, immediately after.
        ids = [pane.id for pane in app.query_one(TabbedContent).query(TabPane)]
        assert ids.index("tab-ollama") == ids.index("tab-logs") + 1
        # Dedicated Ollama log shows the external-server hint on mount (once sized).
        app.query_one(TabbedContent).active = "tab-ollama"
        await pilot.pause()
        ollama_log = app.query_one("#ollamalog", RichLog)
        assert "Restart LLM" in "\n".join(str(line) for line in ollama_log.lines)


async def test_health_badge_reflects_up(monkeypatch):
    monkeypatch.setattr(discovery, "ollama_health", _fake_health(True))
    app = AssistantTUI(supervisor=FakeSupervisor(), ollama=FakeSupervisor())
    async with app.run_test() as pilot:
        await pilot.pause()
        assert "ollama: up" in str(app.query_one("#ollama-status", Static).render())
        assert "ollama up" in str(app.query_one("#status", Static).render())


async def test_health_badge_reflects_down(monkeypatch):
    monkeypatch.setattr(discovery, "ollama_health", _fake_health(False))
    app = AssistantTUI(supervisor=FakeSupervisor(), ollama=FakeSupervisor())
    async with app.run_test() as pilot:
        await pilot.pause()
        assert "ollama: DOWN" in str(app.query_one("#ollama-status", Static).render())
        assert "ollama DOWN" in str(app.query_one("#status", Static).render())
