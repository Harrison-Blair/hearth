"""Backend configuration loaded from YAML, environment, and ``.env``."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import ClassVar, Self
from urllib.parse import urlparse

from dotenv import dotenv_values
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)
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


_CONFIG_NAME_RULE = r"[a-z0-9]+([_-][a-z0-9]+)*"
_CONFIG_NAME_PATTERN = re.compile(_CONFIG_NAME_RULE)


def _validate_config_map_name(kind: str, name: str) -> None:
    if _CONFIG_NAME_PATTERN.fullmatch(name) is None:
        raise ValueError(f'{kind} name "{name}" must match {_CONFIG_NAME_RULE}')


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class ServerConfig(_Model):
    host: str = Field(default="0.0.0.0", description="Interface to bind")
    port: int = Field(default=8765, ge=0, le=65535, description="TCP port, 0 picks a free port")


class ProviderConfig(_Model):
    base_url: str = Field(description="OpenAI-compatible API base URL")
    api_key_env: str | None = Field(
        default=None, description="Environment variable that holds the API key"
    )

    @field_validator("base_url")
    @classmethod
    def _validate_base_url(cls, value: str) -> str:
        parsed = urlparse(value)
        try:
            host = parsed.hostname
            _ = parsed.port
        except ValueError as exc:
            raise ValueError("base_url has an invalid host or port") from exc
        if (
            parsed.scheme not in {"http", "https"}
            or not host
            or any(character.isspace() for character in value)
        ):
            raise ValueError("base_url must be an http(s) URL with a host")
        return value


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
        hide_input_in_errors=True,
    )

    server: ServerConfig = Field(default_factory=ServerConfig)
    providers: dict[str, ProviderConfig]
    roles: dict[str, RoleConfig]
    history: HistoryConfig = Field(default_factory=HistoryConfig)
    events: EventsConfig = Field(default_factory=EventsConfig)
    llm: LlmConfig = Field(default_factory=LlmConfig)

    _yaml_file: ClassVar[Path] = DEFAULT_CONFIG_PATH

    @model_validator(mode="after")
    def _validate_config(self) -> Self:
        for provider_name in self.providers:
            _validate_config_map_name("provider", provider_name)
        for role_name in self.roles:
            _validate_config_map_name("role", role_name)
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


def read_api_key(
    provider: ProviderConfig,
    *,
    env_file: Path = Path(".env"),
) -> str | None:
    """Return a provider's key from the environment or .env, if present."""
    if provider.api_key_env is None:
        return None
    key = os.environ.get(provider.api_key_env)
    if not key and env_file.is_file():
        key = dotenv_values(env_file).get(provider.api_key_env)
    return key or None


def configured_api_keys(
    config: BackendConfig,
    *,
    env_file: Path = Path(".env"),
) -> tuple[str, ...]:
    """Return every resolvable provider key so error details can redact them."""
    return tuple(
        key
        for provider in config.providers.values()
        if (key := read_api_key(provider, env_file=env_file)) is not None
    )


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

    key = read_api_key(provider, env_file=env_file)
    if key is None:
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
    "configured_api_keys",
    "load_config",
    "read_api_key",
]
