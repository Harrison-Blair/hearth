"""Tests for hearth.config: YAML base -> HEARTH_* env -> .env secret precedence."""
import os
from pathlib import Path

import pytest
import yaml

from hearth.config import Settings, resolve_config_path

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
gateway:
  host: 0.0.0.0
  port: 9999
storage:
  db_path: hearth.db
conversation:
  max_history_turns: 12
"""


@pytest.fixture
def config_yaml(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    path = config_dir / "engine.yaml"
    path.write_text(YAML_CONTENT)
    monkeypatch.setattr("hearth.config.CONFIG_DIR", config_dir)
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


def test_dotenv_loads_when_env_unset(config_yaml, tmp_path, monkeypatch):
    _clear_hearth_env(monkeypatch)
    env_file = tmp_path / ".env"
    env_file.write_text("HEARTH_STORAGE__DB_PATH=dotenv.db\n")
    settings = Settings(_env_file=str(env_file))
    assert settings.storage.db_path == "dotenv.db"


def test_exported_env_beats_dotenv(config_yaml, tmp_path, monkeypatch):
    _clear_hearth_env(monkeypatch)
    env_file = tmp_path / ".env"
    env_file.write_text("HEARTH_STORAGE__DB_PATH=dotenv.db\n")
    monkeypatch.setenv("HEARTH_STORAGE__DB_PATH", "exported.db")
    settings = Settings(_env_file=str(env_file))
    assert settings.storage.db_path == "exported.db"


def test_hearth_config_env_var_wins(config_yaml, tmp_path, monkeypatch):
    _clear_hearth_env(monkeypatch)
    override = tmp_path / "elsewhere.yaml"
    override.write_text(YAML_CONTENT.replace("db_path: hearth.db", "db_path: elsewhere.db"))
    monkeypatch.setenv("HEARTH_CONFIG", str(override))
    settings = Settings(_env_file=None)
    assert settings.storage.db_path == "elsewhere.db"


def test_hearth_config_pointing_at_missing_file_raises(config_yaml, tmp_path, monkeypatch):
    _clear_hearth_env(monkeypatch)
    monkeypatch.setenv("HEARTH_CONFIG", str(tmp_path / "nope.yaml"))
    with pytest.raises(FileNotFoundError, match="HEARTH_CONFIG"):
        Settings(_env_file=None)


def test_cwd_config_used_when_packaged_default_missing(tmp_path, monkeypatch):
    _clear_hearth_env(monkeypatch)
    monkeypatch.setattr("hearth.config.CONFIG_DIR", tmp_path / "absent")
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "engine.yaml").write_text(YAML_CONTENT)
    monkeypatch.chdir(tmp_path)
    settings = Settings(_env_file=None)
    assert settings.storage.db_path == "hearth.db"


def test_no_config_anywhere_fails_loud(tmp_path, monkeypatch):
    _clear_hearth_env(monkeypatch)
    monkeypatch.setattr("hearth.config.CONFIG_DIR", tmp_path / "absent")
    monkeypatch.chdir(tmp_path)
    with pytest.raises(FileNotFoundError, match="config/defaults/engine.yaml"):
        Settings(_env_file=None)


@pytest.mark.parametrize("component", ["engine", "chat"])
def test_resolver_targets_named_component_file(tmp_path, monkeypatch, component):
    _clear_hearth_env(monkeypatch)
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    target = config_dir / f"{component}.yaml"
    target.write_text(YAML_CONTENT)
    monkeypatch.setattr("hearth.config.CONFIG_DIR", config_dir, raising=False)
    assert resolve_config_path(component) == target


def test_missing_component_config_fails_loud(tmp_path, monkeypatch):
    _clear_hearth_env(monkeypatch)
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    monkeypatch.setattr("hearth.config.CONFIG_DIR", config_dir, raising=False)
    monkeypatch.chdir(tmp_path)
    with pytest.raises(FileNotFoundError, match="chat.yaml"):
        resolve_config_path("chat")


def test_engine_config_exposes_gateway_section(tmp_path, monkeypatch):
    _clear_hearth_env(monkeypatch)
    cfg = tmp_path / "engine.yaml"
    cfg.write_text(YAML_CONTENT)
    monkeypatch.setenv("HEARTH_CONFIG", str(cfg))
    settings = Settings(_env_file=None)
    assert settings.gateway.host == "0.0.0.0"
    assert settings.gateway.port == 9999


def _load_default_persona_prompt():
    default_config_path = Path(__file__).parent.parent / "config" / "defaults" / "engine.yaml"
    data = yaml.safe_load(default_config_path.read_text())
    return data["persona"]["system_prompt"]


def test_default_persona_prompt_is_vesta():
    prompt = _load_default_persona_prompt()
    assert "You are Vesta." in prompt
    assert "calcifer" not in prompt.lower()


def test_default_persona_prompt_has_no_mythological_titles():
    prompt = _load_default_persona_prompt()
    lowered = prompt.lower()
    assert "goddess" not in lowered
    assert "keeper of the" not in lowered


def test_default_persona_prompt_has_deescalation_rule():
    prompt = _load_default_persona_prompt()
    assert "de-escalat" in prompt.lower()


def test_default_persona_prompt_retains_consult_brain_instruction():
    prompt = _load_default_persona_prompt()
    assert "consult_brain" in prompt
