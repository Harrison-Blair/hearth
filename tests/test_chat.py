"""Chat veneer: fail-fast on an unreachable engine, and config independence."""
from __future__ import annotations

import os
import socket

import pytest


def _clear_hearth_env(monkeypatch):
    for key in list(os.environ):
        if key.startswith("HEARTH_"):
            monkeypatch.delenv(key, raising=False)


def _closed_port() -> int:
    """Bind an ephemeral port and release it, so connecting to it refuses."""
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def test_chat_fails_fast_on_unreachable_engine(tmp_path, monkeypatch, capsys):
    """Pointed at a closed port, chat prints a plain message naming the host
    and port it tried and that the engine may not be running, exits non-zero,
    and prints NO traceback."""
    _clear_hearth_env(monkeypatch)
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "chat.yaml").write_text("engine:\n  host: 127.0.0.1\n  port: 8765\n")
    monkeypatch.setattr("hearth.config.CONFIG_DIR", config_dir, raising=False)
    monkeypatch.chdir(tmp_path)

    port = _closed_port()
    monkeypatch.setenv("HEARTH_ENGINE__HOST", "127.0.0.1")
    monkeypatch.setenv("HEARTH_ENGINE__PORT", str(port))

    from hearth.veneers.chat.__main__ import main

    exit_code = main()

    captured = capsys.readouterr()
    combined = captured.out + captured.err

    assert exit_code != 0
    assert "127.0.0.1" in combined
    assert str(port) in combined
    assert "running" in combined.lower()  # "...the engine may not be running"
    assert "Traceback" not in combined


def test_chat_loads_only_its_own_config(tmp_path, monkeypatch):
    """Chat loads config/chat.yaml and reads engine.host/engine.port, and does
    NOT require the engine's config to be present at all (FC-9)."""
    _clear_hearth_env(monkeypatch)
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "chat.yaml").write_text("engine:\n  host: 10.0.0.5\n  port: 4321\n")
    monkeypatch.setattr("hearth.config.CONFIG_DIR", config_dir, raising=False)
    monkeypatch.chdir(tmp_path)  # cwd fallback also only sees config/chat.yaml

    from hearth.veneers.chat.config import ChatSettings

    settings = ChatSettings()
    assert settings.engine.host == "10.0.0.5"
    assert settings.engine.port == 4321

    # The engine's config is absent, yet chat loaded fine -- the two are
    # independent. Prove the engine genuinely cannot load here.
    from hearth.config import Settings

    with pytest.raises(FileNotFoundError):
        Settings(_env_file=None)
