"""hearth configuration schema.

Loaded via pydantic-settings with precedence YAML base -> .env (secrets
only) -> exported HEARTH_* env. Secrets never live on the YAML-facing model:
fields that hold a secret (e.g. an LLM backend's API key) are resolved from
the env var named in `api_key_env`, not stored as a config field.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from pydantic import BaseModel
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)

CONFIG_YAML_PATH = Path(__file__).resolve().parent.parent / "config.yaml"


def resolve_config_path() -> Path:
    """Locate the active config.yaml, failing loud when none exists.

    Order: `HEARTH_CONFIG` env var (must point at an existing file), the
    package-adjacent default (a source checkout; also the PyInstaller bundle
    root), then ./config.yaml in the working directory (wheel installs run
    from a config-carrying directory). A missing config used to load silently
    as empty and surface later as a bare KeyError in the router -- raise a
    clear error at construction instead."""
    env_path = os.environ.get("HEARTH_CONFIG")
    if env_path:
        path = Path(env_path)
        if not path.is_file():
            raise FileNotFoundError(f"HEARTH_CONFIG points to a missing file: {path}")
        return path
    if CONFIG_YAML_PATH.is_file():
        return CONFIG_YAML_PATH
    cwd_path = Path.cwd() / "config.yaml"
    if cwd_path.is_file():
        return cwd_path
    raise FileNotFoundError(
        "no config.yaml found: copy default-config.yaml to config.yaml "
        f"(looked in {CONFIG_YAML_PATH} and {cwd_path}) or set HEARTH_CONFIG"
    )


class LLMBackend(BaseModel):
    base_url: str = ""
    model: str
    api_key_env: Optional[str] = None
    supports_tools: bool = False
    supports_streaming: bool = False
    context_window: int = 8192
    cost_tier: str = "free"
    enabled: bool = True

    def resolve_api_key(self) -> Optional[str]:
        """Read the API key from the env var named by `api_key_env`, if any."""
        if not self.api_key_env:
            return None
        return os.environ.get(self.api_key_env)


class LLMTiers(BaseModel):
    default: str = "local"
    tool: str = "remote"


class LLMConfig(BaseModel):
    backends: dict[str, LLMBackend] = {}
    tiers: LLMTiers = LLMTiers()
    timeout: float = 60.0
    max_retries: int = 2

    def resolve_tier(self, tier: str) -> LLMBackend:
        """Resolve a tier role (e.g. "default", "tool") to its backend config."""
        backend_name = getattr(self.tiers, tier)
        return self.backends[backend_name]


class VeneerConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8765


class ToolConfig(BaseModel):
    wikipedia_enabled: bool = True
    wikipedia_language: str = "en"
    wikipedia_endpoint: str = "/w/rest.php/v1/search/page"
    wikipedia_result_count: int = 3
    wikipedia_max_chars: int = 1000
    wikipedia_timeout: float = 10.0


class AgentConfig(BaseModel):
    max_tool_rounds: int = 3
    turn_timeout_s: float = 45.0
    tool_mode: str = "auto"
    max_consult_rounds: int = 3
    consult_timeout_s: float = 30.0


class PersonaConfig(BaseModel):
    enabled: bool = True
    system_prompt: str = ""
    brain_guard_prompt: str = ""


class ConversationConfig(BaseModel):
    max_history_turns: int = 12


class StorageConfig(BaseModel):
    db_path: str = "hearth.db"


class LoggingConfig(BaseModel):
    level: str = "INFO"
    dir: str = "logs"
    file_name: str = "hearth.log"
    max_bytes: int = 1_000_000
    backup_count: int = 5
    console: bool = True
    transcript_enabled: bool = True
    transcript_dir: str = "logs/transcripts"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="HEARTH_",
        env_nested_delimiter="__",
        env_file=".env",
        extra="ignore",
    )

    llm: LLMConfig = LLMConfig()
    veneer: VeneerConfig = VeneerConfig()
    tool: ToolConfig = ToolConfig()
    agent: AgentConfig = AgentConfig()
    persona: PersonaConfig = PersonaConfig()
    conversation: ConversationConfig = ConversationConfig()
    storage: StorageConfig = StorageConfig()
    logging: LoggingConfig = LoggingConfig()

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls,
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        # Precedence, highest first: init kwargs, exported HEARTH_* env, .env
        # secrets, config.yaml base, file secrets. An exported env var beats
        # the same key in .env -- the conventional order, and it matches
        # app.py's load_dotenv(), which never overrides existing process env.
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            YamlConfigSettingsSource(settings_cls, yaml_file=resolve_config_path()),
            file_secret_settings,
        )
