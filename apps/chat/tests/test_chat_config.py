"""Chat configuration loading and environment overrides."""

from __future__ import annotations

from pathlib import Path

import pytest

from hearth.chat.config import ChatConfigError, load_config

ROOT = Path(__file__).resolve().parents[3]


def test_chat_example_has_comments_and_loads() -> None:
    path = ROOT / "config" / "chat.example.yaml"
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            assert "#" in line, f"{path}:{number} has no comment: {line}"

    config = load_config(path)

    assert config.backend_url == "ws://127.0.0.1:8765"
    assert config.device_id == "desk"
    assert config.token == "replace-with-device-token"


def test_token_can_come_from_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HEARTH_CHAT__TOKEN", "from-environment")

    config = load_config(ROOT / "config" / "chat.example.yaml")

    assert config.token == "from-environment"


def test_token_can_come_from_dotenv(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("HEARTH_CHAT__TOKEN=from-dotenv\n", encoding="utf-8")

    config = load_config(ROOT / "config" / "chat.example.yaml")

    assert config.token == "from-dotenv"


def test_invalid_backend_url_in_yaml_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "chat.yaml"
    path.write_text(
        "backend_url: http://127.0.0.1:8765\ndevice_id: desk\ntoken: token\n",
        encoding="utf-8",
    )

    with pytest.raises(ChatConfigError, match="backend_url"):
        load_config(path)


def test_invalid_backend_url_env_override_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HEARTH_CHAT__BACKEND_URL", "not-a-url")

    with pytest.raises(ChatConfigError, match="backend_url"):
        load_config(ROOT / "config" / "chat.example.yaml")


def test_missing_chat_config_is_a_clear_error(tmp_path: Path) -> None:
    with pytest.raises(ChatConfigError, match="config file not found"):
        load_config(tmp_path / "missing.yaml")


def test_invalid_chat_yaml_is_a_clear_error(tmp_path: Path) -> None:
    path = tmp_path / "bad.yaml"
    path.write_text("backend_url: [unclosed\n", encoding="utf-8")

    with pytest.raises(ChatConfigError, match="invalid YAML"):
        load_config(path)
