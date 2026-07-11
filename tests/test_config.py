"""Tests for hearth.config: YAML base -> HEARTH_* env -> .env secret precedence."""
import os

import pytest

from hearth.config import Settings

YAML_CONTENT = """
llm:
  backends:
    local:
      base_url: http://localhost:11434/v1
      model: qwen3:14b
      api_key_env: null
      supports_tools: true
      supports_streaming: true
      context_window: 8192
      cost_tier: free
      enabled: true
    remote:
      base_url: ''
      model: openrouter/free
      api_key_env: HEARTH_LLM__OPENROUTER_API_KEY
      supports_tools: true
      supports_streaming: true
      context_window: 8192
      cost_tier: free
      enabled: true
  tiers:
    default: local
    tool: remote
  timeout: 60.0
  max_retries: 2
veneer:
  host: 127.0.0.1
  port: 8765
storage:
  db_path: hearth.db
conversation:
  max_history_turns: 12
"""


@pytest.fixture
def config_yaml(tmp_path, monkeypatch):
    path = tmp_path / "config.yaml"
    path.write_text(YAML_CONTENT)
    monkeypatch.setattr("hearth.config.CONFIG_YAML_PATH", path)
    return path


def _clear_hearth_env(monkeypatch):
    for key in list(os.environ):
        if key.startswith("HEARTH_"):
            monkeypatch.delenv(key, raising=False)


def test_config_loads_yaml_base(config_yaml, monkeypatch):
    _clear_hearth_env(monkeypatch)
    settings = Settings(_env_file=None)
    assert settings.llm.backends["local"].model == "qwen3:14b"
    assert settings.llm.backends["remote"].model == "openrouter/free"
    assert settings.llm.tiers.default == "local"
    assert settings.storage.db_path == "hearth.db"
    assert settings.veneer.port == 8765


def test_env_overrides_yaml(config_yaml, monkeypatch):
    _clear_hearth_env(monkeypatch)
    monkeypatch.setenv("HEARTH_STORAGE__DB_PATH", "override.db")
    settings = Settings(_env_file=None)
    assert settings.storage.db_path == "override.db"


def test_secret_from_env_only(config_yaml, monkeypatch):
    _clear_hearth_env(monkeypatch)
    monkeypatch.setenv("HEARTH_LLM__OPENROUTER_API_KEY", "sk-test-123")
    settings = Settings(_env_file=None)
    remote = settings.llm.backends["remote"]
    assert "api_key" not in type(remote).model_fields
    assert remote.resolve_api_key() == "sk-test-123"


def test_tier_roles_resolve(config_yaml, monkeypatch):
    _clear_hearth_env(monkeypatch)
    settings = Settings(_env_file=None)
    assert settings.llm.resolve_tier("default").model == "qwen3:14b"
    assert settings.llm.resolve_tier("tool").model == "openrouter/free"
