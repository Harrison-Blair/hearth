"""Chat client configuration."""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

from pydantic import Field, ValidationError
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)
from yaml import YAMLError

DEFAULT_CONFIG_PATH = Path("config/chat.yaml")


class ChatConfigError(Exception):
    """Raised when the chat configuration cannot be loaded."""


class ChatConfig(BaseSettings):
    """Chat settings, with ``HEARTH_CHAT__*`` environment variables overriding YAML."""

    model_config = SettingsConfigDict(
        env_prefix="HEARTH_CHAT__",
        env_nested_delimiter="__",
        env_file=".env",
        dotenv_filtering="only_existing",
        extra="forbid",
    )

    backend_url: str = Field(description="Backend WebSocket URL")
    device_id: str = Field(description="Registered device id")
    token: str = Field(description="Device token")

    _yaml_file: ClassVar[Path] = DEFAULT_CONFIG_PATH

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


def load_config(path: Path = DEFAULT_CONFIG_PATH) -> ChatConfig:
    """Load and validate the chat configuration from ``path``."""
    if not path.is_file():
        raise ChatConfigError(f"config file not found: {path}")

    class _LoadedConfig(ChatConfig):
        _yaml_file = path

    try:
        # pydantic-settings fills required fields from YAML and environment sources.
        return _LoadedConfig()  # pyright: ignore[reportCallIssue]
    except ValidationError as exc:
        raise ChatConfigError(f"invalid config {path}:\n{exc}") from exc
    except YAMLError as exc:
        raise ChatConfigError(f"invalid YAML in {path}:\n{exc}") from exc
