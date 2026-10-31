"""Backend configuration loading and validation."""

from __future__ import annotations

from pathlib import Path

import pytest

from hearth.backend.config import (
    BackendConfig,
    ConfigError,
    api_key_for,
    load_config,
)

ROOT = Path(__file__).resolve().parents[3]


def _assert_every_field_has_a_comment(path: Path) -> None:
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            assert "#" in line, f"{path}:{number} has no comment: {line}"


def test_backend_example_has_comments_and_loads() -> None:
    path = ROOT / "config" / "backend.example.yaml"
    _assert_every_field_has_a_comment(path)

    config = load_config(path)

    assert config.server.port == 8765
    assert config.roles["fast"].model == "gemma4:e2b"
    assert config.providers["openrouter"].api_key_env == "OPENROUTER_API_KEY"
    assert config.history.max_turns == 20


def test_environment_overrides_nested_yaml(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HEARTH_SERVER__PORT", "9999")
    monkeypatch.setenv("HEARTH_HISTORY__MAX_TURNS", "3")
    monkeypatch.setenv("HEARTH_PROVIDERS__LOCAL__BASE_URL", "http://env.example/v1")

    config = load_config(ROOT / "config" / "backend.example.yaml")

    assert config.server.port == 9999
    assert config.history.max_turns == 3
    assert config.providers["local"].base_url == "http://env.example/v1"


def test_dotenv_overrides_yaml_and_may_hold_a_key(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text(
        "HEARTH_SERVER__PORT=7777\nOPENROUTER_API_KEY=not-a-config-field\n",
        encoding="utf-8",
    )

    config = load_config(ROOT / "config" / "backend.example.yaml")

    assert config.server.port == 7777


def test_invalid_provider_url_in_yaml_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "backend.yaml"
    path.write_text(
        "providers:\n"
        "  local:\n"
        "    base_url: http://\n"
        "roles:\n"
        "  fast:\n"
        "    provider: local\n"
        "    model: m\n",
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="base_url"):
        load_config(path)


def test_invalid_provider_url_env_override_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HEARTH_PROVIDERS__LOCAL__BASE_URL", "ftp://example.com/v1")

    with pytest.raises(ConfigError, match="base_url"):
        load_config(ROOT / "config" / "backend.example.yaml")


def test_missing_config_file_is_a_clear_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="config file not found"):
        load_config(tmp_path / "missing.yaml")


def test_invalid_yaml_is_a_clear_error(tmp_path: Path) -> None:
    path = tmp_path / "bad.yaml"
    path.write_text("server: [unclosed\n", encoding="utf-8")

    with pytest.raises(ConfigError, match="invalid YAML"):
        load_config(path)


def test_api_key_field_in_yaml_is_rejected() -> None:
    with pytest.raises(ValueError, match="api_key"):
        BackendConfig.model_validate(
            {
                "providers": {
                    "remote": {
                        "base_url": "https://example.invalid/v1",
                        "api_key": "not-allowed-in-yaml",
                    }
                },
                "roles": {"fast": {"provider": "remote", "model": "m"}},
            }
        )


def test_unknown_role_provider_fails_validation() -> None:
    with pytest.raises(ValueError, match="roles.fast.provider"):
        BackendConfig.model_validate(
            {
                "providers": {"local": {"base_url": "http://localhost:11434/v1"}},
                "roles": {"fast": {"provider": "missing", "model": "m"}},
            }
        )


def test_fast_role_is_required() -> None:
    with pytest.raises(ValueError, match="roles.fast is required"):
        BackendConfig.model_validate(
            {
                "providers": {"local": {"base_url": "http://localhost:11434/v1"}},
                "roles": {"slow": {"provider": "local", "model": "m"}},
            }
        )


def _keyed_config() -> BackendConfig:
    return BackendConfig.model_validate(
        {
            "providers": {
                "remote": {
                    "base_url": "https://example.invalid/v1",
                    "api_key_env": "TEST_API_KEY",
                }
            },
            "roles": {"fast": {"provider": "remote", "model": "m"}},
        }
    )


def test_api_key_comes_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TEST_API_KEY", "from-environment")
    assert api_key_for(_keyed_config(), "fast") == "from-environment"


def test_api_key_can_come_from_dotenv(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv("TEST_API_KEY", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text("TEST_API_KEY=from-dotenv\n", encoding="utf-8")

    assert api_key_for(_keyed_config(), "fast", env_file=env_file) == "from-dotenv"


def test_missing_api_key_is_a_clear_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv("TEST_API_KEY", raising=False)

    with pytest.raises(ConfigError, match="TEST_API_KEY"):
        api_key_for(_keyed_config(), "fast", env_file=tmp_path / "absent.env")


def test_provider_without_api_key_env_uses_placeholder() -> None:
    config = BackendConfig.model_validate(
        {
            "providers": {"local": {"base_url": "http://localhost:11434/v1"}},
            "roles": {"fast": {"provider": "local", "model": "m"}},
        }
    )
    assert api_key_for(config, "fast") == "not-needed"
