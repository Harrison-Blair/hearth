"""Tests for hearth.app CLI entry point."""
import logging

from hearth import __version__
from hearth.app import _build_llm_clients, _run_daemon, main


async def test_build_llm_clients_wires_configured_timeout(llm_config):
    """Every LLM httpx client must carry settings.llm.timeout, not httpx's
    5s default -- otherwise any generation over 5s trips a read timeout and
    surfaces as "backend unreachable" (the "only one turn" bug)."""

    class _Settings:
        class llm:
            timeout = 37.0
            backends = llm_config.backends

    clients = _build_llm_clients(_Settings)
    try:
        assert clients  # at least one backend
        for client in clients.values():
            assert client.timeout.read == 37.0
            assert client.timeout.connect == 37.0
    finally:
        for client in clients.values():
            await client.aclose()


def test_version_command(capsys):
    exit_code = main(["--version"])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out.strip() == __version__


async def test_run_daemon_wires_wikipedia_tool_brain_side(monkeypatch, tmp_path):
    """_run_daemon must build a ToolRegistry (from settings.tool + its own
    httpx client) and hand it to a `BrainConsult` injected into `Loop` --
    otherwise `hearth run` never actually exposes the wikipedia tool, even
    though it's now only reachable via the nested consult_brain loop
    (FTHR-009; wikipedia moved off the top-level orchestrator)."""
    captured = {}

    class _FakeGateway:
        def __init__(self, loop, log, config) -> None:
            captured["loop"] = loop

        async def serve(self, host=None, port=None) -> None:
            return None

    monkeypatch.chdir(tmp_path)  # keep the sqlite db out of the worktree
    monkeypatch.setattr("hearth.gateway.server.Gateway", _FakeGateway)

    exit_code = await _run_daemon()

    assert exit_code == 0
    registry = captured["loop"]._consult._tool_registry
    assert registry.specs() != []  # config.yaml's wikipedia_enabled: true


async def test_run_daemon_logs_server_lifecycle_lines(monkeypatch, tmp_path, caplog):
    """_run_daemon must emit "daemon starting" and "gateway serving" INFO
    lines tagged extra={"category": "server"} so FTHR-016's console
    formatter can color the daemon's lifecycle distinctly -- today app.py
    has no logger at all, so no such records exist."""

    class _FakeGateway:
        def __init__(self, loop, log, config) -> None:
            pass

        async def serve(self, host=None, port=None) -> None:
            return None

    monkeypatch.chdir(tmp_path)  # keep the sqlite db out of the worktree
    monkeypatch.setattr("hearth.gateway.server.Gateway", _FakeGateway)

    with caplog.at_level(logging.INFO):
        exit_code = await _run_daemon()

    assert exit_code == 0
    server_records = [r for r in caplog.records if getattr(r, "category", None) == "server"]
    messages = [r.getMessage() for r in server_records]
    assert any("daemon starting" in m for m in messages)
    assert any("gateway serving" in m for m in messages)


async def test_engine_binds_via_gateway_config(monkeypatch, tmp_path):
    """_run_daemon must serve on settings.gateway.host/.port, not the deleted
    settings.veneer. The dead HEARTH_VENEER__* env influences nothing."""
    captured = {}

    class _FakeGateway:
        def __init__(self, loop, log, config) -> None:
            pass

        async def serve(self, host=None, port=None) -> None:
            captured["host"] = host
            captured["port"] = port

    monkeypatch.chdir(tmp_path)  # keep the sqlite db out of the worktree
    monkeypatch.setattr("hearth.gateway.server.Gateway", _FakeGateway)
    monkeypatch.setenv("HEARTH_GATEWAY__HOST", "0.0.0.0")
    monkeypatch.setenv("HEARTH_GATEWAY__PORT", "4321")
    monkeypatch.setenv("HEARTH_VENEER__PORT", "9999")  # dead section: must be ignored

    exit_code = await _run_daemon()

    assert exit_code == 0
    assert captured["host"] == "0.0.0.0"
    assert captured["port"] == 4321
