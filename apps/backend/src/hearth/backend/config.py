"""Backend configuration loaded from YAML, environment, and ``.env``."""

from __future__ import annotations

import os
from pathlib import Path
from typing import ClassVar, Self

from dotenv import dotenv_values
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)
from yaml import YAMLError

DEFAULT_CONFIG_PATH = Path("config/backend.yaml")
DEFAULT_DEVICES_PATH = Path("config/devices.yaml")


class ConfigError(Exception):
    """Raised when the configuration cannot be loaded or is not usable."""


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ServerConfig(_Model):
    host: str = Field(default="0.0.0.0", description="Interface to bind")
    port: int = Field(default=8765, ge=0, le=65535, description="TCP port, 0 picks a free port")


class ProviderConfig(_Model):
    base_url: str = Field(description="OpenAI-compatible API base URL")
    api_key_env: str | None = Field(
        default=None, description="Environment variable that holds the API key"
    )


class RoleConfig(_Model):
    provider: str = Field(description="Provider name from the providers mapping")
    model: str = Field(description="Model name sent to the provider")


class HistoryConfig(_Model):
    window_minutes: int = Field(default=10, gt=0, description="Age limit for history turns")
    max_turns: int = Field(default=20, ge=1, description="Maximum history turns in a prompt")


class EventsConfig(_Model):
    dir: Path = Field(default=Path("data/events"), description="Directory for daily JSONL files")


class LlmConfig(_Model):
    timeout_s: float = Field(default=30.0, gt=0, description="LLM request timeout in seconds")


class BackendConfig(BaseSettings):
    """Validated backend settings.

    Precedence is init arguments, environment (``HEARTH_*``, nested with
    ``__``), ``.env``, then YAML.
    """

    model_config = SettingsConfigDict(
        env_prefix="HEARTH_",
        env_nested_delimiter="__",
        env_file=".env",
        dotenv_filtering="only_existing",
        extra="forbid",
    )

    server: ServerConfig = Field(default_factory=ServerConfig)
    providers: dict[str, ProviderConfig]
    roles: dict[str, RoleConfig]
    history: HistoryConfig = Field(default_factory=HistoryConfig)
    events: EventsConfig = Field(default_factory=EventsConfig)
    llm: LlmConfig = Field(default_factory=LlmConfig)

    _yaml_file: ClassVar[Path] = DEFAULT_CONFIG_PATH

    @model_validator(mode="after")
    def _check_roles(self) -> Self:
        if "fast" not in self.roles:
            raise ValueError("roles.fast is required")
        for name, role in self.roles.items():
            if role.provider not in self.providers:
                raise ValueError(f"roles.{name}.provider {role.provider!r} is not in providers")
        return self

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            YamlConfigSettingsSource(settings_cls, yaml_file=cls._yaml_file),
            file_secret_settings,
        )


def load_config(path: Path = DEFAULT_CONFIG_PATH) -> BackendConfig:
    """Load and validate the backend configuration from ``path``."""

    if not path.is_file():
        raise ConfigError(f"config file not found: {path}")

    class _LoadedConfig(BackendConfig):
        _yaml_file = path

    try:
        # pydantic-settings fills required fields from YAML and environment sources.
        return _LoadedConfig()  # pyright: ignore[reportCallIssue]
    except ValidationError as exc:
        raise ConfigError(f"invalid config {path}:\n{exc}") from exc
    except YAMLError as exc:
        raise ConfigError(f"invalid YAML in {path}:\n{exc}") from exc


def api_key_for(
    config: BackendConfig,
    role: str,
    *,
    env_file: Path = Path(".env"),
) -> str:
    """Return the API key for a role, or a placeholder when the provider needs none."""

    role_config = config.roles[role]
    provider = config.providers[role_config.provider]
    if provider.api_key_env is None:
        return "not-needed"

    key = os.environ.get(provider.api_key_env)
    if not key and env_file.is_file():
        key = dotenv_values(env_file).get(provider.api_key_env)
    if not key:
        raise ConfigError(
            f"provider {role_config.provider!r} requires {provider.api_key_env}; "
            "set it in the environment or .env"
        )
    return key


__all__ = [
    "BackendConfig",
    "ConfigError",
    "DEFAULT_CONFIG_PATH",
    "DEFAULT_DEVICES_PATH",
    "EventsConfig",
    "HistoryConfig",
    "LlmConfig",
    "ProviderConfig",
    "RoleConfig",
    "ServerConfig",
    "api_key_for",
    "load_config",
]
