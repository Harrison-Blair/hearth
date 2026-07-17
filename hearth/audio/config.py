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

    aggressiveness: int = 2  # webrtcvad range 0-3 (higher = filters more non-speech)
    silence_ms: int = 800
    max_utterance_ms: int = 12000


class STTConfig(BaseModel):
    """Transcription model + params consumed by FTHR-031's transcriber. The four
    knobs are the stenographer-proven defaults (FC-6), tunable on the Pi without
    a code edit (the Pi may need a lighter model)."""

    model: str = "Systran/faster-distil-whisper-medium.en"
    compute_type: str = "int8"
    beam_size: int = 5
    language: str = "en"


class RetryConfig(BaseModel):
    """Connection retry/backoff for an unattended surface (FC-10)."""

    max_attempts: int = 30
    base_delay_s: float = 1.0


class PresentationConfig(BaseModel):
    """Per-tag ANSI colours for the `[heard]`/`[spoken]` presentation (FC-9), so
    heard and spoken lines read distinctly. Matches the surface family's
    `[<colour>tag<reset>]` styling (cf. `hearth-chat`'s answer line). The
    speaking-side FTHR-035 addition; the listening side stays as FTHR-028 left it."""

    heard_color: str = "36"  # cyan
    spoken_color: str = "35"  # magenta

    def colors(self) -> dict[str, str]:
        """Tag -> ANSI colour code, the shape the surface's `present_line` reads."""
        return {"heard": self.heard_color, "spoken": self.spoken_color}


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
    # --- speaking (FTHR-035) --------------------------------------------------
    # `voice` has NO shipped default: an unset voice is representable as missing
    # (None), which FTHR-037 turns into the first-run acquisition error. This
    # feather defines the no-default stance in the schema; it does not implement
    # the absent-voice behaviour. Never silently falls back to some voice.
    voice: str | None = None
    # Output device (PortAudio name/index); None = system default (FC-5),
    # mirroring `input_device`. Real device selection is FTHR-038.
    output_device: str | None = None
    presentation: PresentationConfig = PresentationConfig()

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
