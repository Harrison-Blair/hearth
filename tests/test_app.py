"""Tests for hearth.app CLI entry point."""
from hearth import __version__
from hearth.app import _run_daemon, main


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

    class _FakeVeneer:
        def __init__(self, loop, log, config) -> None:
            captured["loop"] = loop

        async def serve(self, host=None, port=None) -> None:
            return None

    monkeypatch.chdir(tmp_path)  # keep the sqlite db out of the worktree
    monkeypatch.setattr("hearth.veneer.server.Veneer", _FakeVeneer)

    exit_code = await _run_daemon()

    assert exit_code == 0
    registry = captured["loop"]._consult._tool_registry
    assert registry.specs() != []  # config.yaml's wikipedia_enabled: true
