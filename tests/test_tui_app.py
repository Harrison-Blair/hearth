from types import SimpleNamespace

from tui import discovery
from tui.app import (
    AssistantTUI,
    _as_option,
    _derive_tier,
    _llm_status_line,
    _ollama_in_chain,
    _provider_label,
)


def test_as_option_normalizes_str_and_tuple():
    # Bare strings become (label, value) with both equal; tuples pass through.
    assert _as_option("llama3.2") == ("llama3.2", "llama3.2")
    assert _as_option(("qwen2.5  —  1.8 GB", "qwen2.5")) == ("qwen2.5  —  1.8 GB", "qwen2.5")


# ---- tiered LLM health helpers -------------------------------------------------


def _llm(provider="ollama", fallback=""):
    return SimpleNamespace(provider=provider, fallback=fallback)


def test_provider_label_shortens_zen():
    assert _provider_label("opencode_zen") == "zen"
    assert _provider_label("ollama") == "ollama"


def test_derive_tier():
    # No fallback configured: up/down on the primary alone (no degraded state).
    assert _derive_tier(True, None) == "up"
    assert _derive_tier(False, None) == "down"
    # Fallback configured: degraded when exactly one side is down.
    assert _derive_tier(True, True) == "up"
    assert _derive_tier(True, False) == "degraded"
    assert _derive_tier(False, True) == "degraded"
    assert _derive_tier(False, False) == "down"


def test_llm_status_line_provider_aware():
    llm = _llm("opencode_zen", "ollama")
    assert _llm_status_line(llm, True, True, "up") == "zen ✓ · ollama ✓"
    assert _llm_status_line(llm, False, True, "degraded") == "zen ✗ · ollama ✓ (degraded)"
    assert _llm_status_line(_llm("ollama"), True, None, "up") == "ollama ✓"
    assert _llm_status_line(_llm("ollama"), False, None, "down") == "ollama ✗"
    # Fits the 40-col status line after the "● " prefix.
    for primary_ok in (True, False):
        for fallback_ok in (True, False):
            tier = _derive_tier(primary_ok, fallback_ok)
            assert len(_llm_status_line(llm, primary_ok, fallback_ok, tier)) <= 38


def test_ollama_in_chain():
    assert _ollama_in_chain(_llm("ollama", "")) is True
    assert _ollama_in_chain(_llm("opencode_zen", "ollama")) is True
    assert _ollama_in_chain(_llm("opencode_zen", "")) is False
    assert _ollama_in_chain(_llm("opencode_zen", "opencode_zen")) is False


# ---- app-level health/gating ----------------------------------------------------


def _fake_config(provider="ollama", fallback=""):
    return SimpleNamespace(
        llm=SimpleNamespace(
            provider=provider,
            fallback=fallback,
            host="http://127.0.0.1:11434",
            base_url="https://zen.example/v1",
            openrouter_api_key="",
            opencode_zen_api_key="sk-test",
            model="qwen2.5:3b",
            serve_cmd=["ollama", "serve"],
        ),
        audio=SimpleNamespace(output_volume=1.0),
        logging=SimpleNamespace(file_enabled=False),
    )


class _FakeSupervisor:
    def __init__(self):
        self.started = 0
        self.running = False

    async def start(self):
        self.started += 1


def _make_app(monkeypatch, provider, fallback=""):
    monkeypatch.setattr(discovery, "current_config", lambda: _fake_config(provider, fallback))
    app = AssistantTUI(supervisor=_FakeSupervisor(), ollama=_FakeSupervisor())
    app._refresh_status = lambda: None
    return app


async def test_check_llm_health_routes_probes_and_derives_tier(monkeypatch):
    calls = []

    async def fake_zen_health(base_url="", api_key="", **_):
        calls.append(("zen", base_url, api_key))
        return False

    async def fake_ollama_health(host="", **_):
        calls.append(("ollama", host))
        return True

    monkeypatch.setattr(discovery, "zen_health", fake_zen_health)
    monkeypatch.setattr(discovery, "ollama_health", fake_ollama_health)
    app = _make_app(monkeypatch, "opencode_zen", "ollama")
    await app._check_llm_health()
    assert ("zen", "https://zen.example/v1", "sk-test") in calls
    assert ("ollama", "http://127.0.0.1:11434") in calls
    assert app._llm_tier == "degraded"
    assert app._llm_status == "zen ✗ · ollama ✓ (degraded)"


async def test_check_llm_health_no_fallback_skips_second_probe(monkeypatch):
    calls = []

    async def fake_zen_health(base_url="", api_key="", **_):
        calls.append("zen")
        return True

    async def fake_ollama_health(host="", **_):
        calls.append("ollama")
        return True

    monkeypatch.setattr(discovery, "zen_health", fake_zen_health)
    monkeypatch.setattr(discovery, "ollama_health", fake_ollama_health)
    app = _make_app(monkeypatch, "opencode_zen")
    await app._check_llm_health()
    assert calls == ["zen"]
    assert app._llm_tier == "up"


async def test_ensure_ollama_skipped_when_ollama_not_in_chain(monkeypatch):
    async def fail_health(*a, **k):  # must not even be probed
        raise AssertionError("ollama_health called for a Zen-only chain")

    monkeypatch.setattr(discovery, "ollama_health", fail_health)
    app = _make_app(monkeypatch, "opencode_zen")
    await app._ensure_ollama()
    assert app.ollama.started == 0


async def test_ensure_ollama_starts_when_ollama_in_chain_and_down(monkeypatch):
    async def fake_ollama_health(host="", **_):
        return False

    async def fake_free_port(host=""):
        return None

    import tui.app as app_module

    monkeypatch.setattr(discovery, "ollama_health", fake_ollama_health)
    monkeypatch.setattr(app_module, "free_ollama_port", fake_free_port)
    app = _make_app(monkeypatch, "opencode_zen", "ollama")
    app._open_ollama_log = lambda: None
    app.run_worker = lambda coro, **k: coro.close()
    await app._ensure_ollama()
    assert app.ollama.started == 1


async def test_ollama_restart_noop_when_not_in_chain(monkeypatch):
    app = _make_app(monkeypatch, "opencode_zen")
    restarted = []
    app.ollama.restart = lambda: restarted.append(True)
    await app._on_ollama_restart()
    assert restarted == []
