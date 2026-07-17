"""Chat's own configuration: which engine to reach.

Read from `config/chat.yaml` via the shared config facility
(`hearth.config.resolve_config_path`, FTHR-022) with the `chat` component --
chat is that facility's second caller. This is the whole of chat's config: it
does not touch the engine's `Settings` (LLM schema, persona, storage), so the
chat process reads two integers without dragging the engine's world into it.
"""
from __future__ import annotations

from pydantic import BaseModel
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)

from hearth.config import resolve_config_path


class EngineEndpoint(BaseModel):
    host: str = "127.0.0.1"
    port: int = 8765


class ChatSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="HEARTH_",
        env_nested_delimiter="__",
        extra="ignore",
    )

    engine: EngineEndpoint = EngineEndpoint()

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls,
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        # Precedence, highest first: init kwargs, exported HEARTH_* env, then
        # config/chat.yaml. Chat has no secrets, so no .env source.
        return (
            init_settings,
            env_settings,
            YamlConfigSettingsSource(settings_cls, yaml_file=resolve_config_path("chat")),
        )
