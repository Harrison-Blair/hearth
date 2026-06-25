"""Typed configuration loaded from config.yaml with ASSISTANT_* env overrides."""

from __future__ import annotations

from pydantic import BaseModel
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)


class AudioConfig(BaseModel):
    # null -> system default; int -> device index; str -> name substring match.
    input: str | int | None = None
    output: str | int | None = None
    sample_rate: int = 16000
    channels: int = 1
    block_size: int = 1280
    output_volume: float = 1.0  # linear gain applied to playback (0.0-1.0+)


class WakeConfig(BaseModel):
    phrase: str = "hey assistant"
    model_path: str | None = None
    model_name: str = "hey_jarvis"
    threshold: float = 0.5


class SttConfig(BaseModel):
    model: str = "base.en"
    compute_type: str = "int8"
    language: str = "en"


class LlmConfig(BaseModel):
    provider: str = "ollama"
    model: str = "qwen2.5:3b-instruct"
    host: str = "http://localhost:11434"
    timeout: float = 60.0
    # Answers are spoken aloud, so steer the model toward short, plain replies.
    system_prompt: str = (
        "You are a helpful voice assistant. Answers are read aloud, so reply in "
        "one or two short, plain sentences. No markdown, lists, or emoji."
    )


class TtsConfig(BaseModel):
    voice: str = "en_US-lessac-medium"
    model_path: str | None = None


class StorageConfig(BaseModel):
    db_path: str = "assistant.db"


class LoggingConfig(BaseModel):
    level: str = "INFO"


class Config(BaseSettings):
    model_config = SettingsConfigDict(
        yaml_file="config.yaml",
        env_prefix="ASSISTANT_",
        env_nested_delimiter="__",
        extra="ignore",
    )

    audio: AudioConfig = AudioConfig()
    wake: WakeConfig = WakeConfig()
    stt: SttConfig = SttConfig()
    llm: LlmConfig = LlmConfig()
    tts: TtsConfig = TtsConfig()
    storage: StorageConfig = StorageConfig()
    logging: LoggingConfig = LoggingConfig()

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        # Precedence: explicit init args > env vars > config.yaml.
        return (init_settings, env_settings, YamlConfigSettingsSource(settings_cls))
