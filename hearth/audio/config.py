"""The audio surface's own configuration (FC-12).

Read from `config/audio.yaml` via the shared config facility
(`hearth.config.resolve_config_path`, FTHR-022) with the `audio` component. Holds
only this surface's settings -- it does not touch the engine's `Settings` (LLM
schema, persona, storage), so the audio process loads independently of the engine.

**The wake-model list schema is the hoist.** `wake_models` is an ordered list of
`{path, threshold}` entries with a **per-model threshold and no global threshold**
(PLM-008 FC-3). This schema is shared surface: FTHR-029 *reads* it to load and
score wake models, and FTHR-032 *writes* it from the training registry. It is
defined **only here** so neither of those feathers redefines it and they never
collide on it.
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


class WakeModel(BaseModel):
    """One entry in the ordered wake-model list. **Per-model** threshold -- there
    is deliberately no global threshold (FC-3). Shared surface: read by FTHR-029,
    written by FTHR-032; defined only here."""

    path: str
    threshold: float


class EndpointConfig(BaseModel):
    """Endpointing / VAD knobs consumed by FTHR-030's endpointer."""

    silence_ms: int = 800
    max_utterance_ms: int = 12000


class STTConfig(BaseModel):
    """Transcription model + params consumed by FTHR-031's transcriber."""

    model: str = "base"
    language: str = "en"


class RetryConfig(BaseModel):
    """Connection retry/backoff for an unattended surface (FC-10)."""

    max_attempts: int = 30
    base_delay_s: float = 1.0


class AudioSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="HEARTH_",
        env_nested_delimiter="__",
        extra="ignore",
    )

    engine: EngineEndpoint = EngineEndpoint()
    input_device: str | None = None
    wake_models: list[WakeModel] = []
    endpoint: EndpointConfig = EndpointConfig()
    stt: STTConfig = STTConfig()
    retry: RetryConfig = RetryConfig()

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
        # config/audio.yaml. The audio surface has no secrets, so no .env source.
        return (
            init_settings,
            env_settings,
            YamlConfigSettingsSource(settings_cls, yaml_file=resolve_config_path("audio")),
        )
