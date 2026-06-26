"""Typed configuration loaded from config.yaml with ASSISTANT_* env overrides."""

from __future__ import annotations

from pydantic import BaseModel
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)

from assistant.wake.registry import phrases_for


class AudioConfig(BaseModel):
    # null -> system default; int -> device index; str -> name substring match.
    input: str | int | None = None
    output: str | int | None = None
    sample_rate: int = 16000
    channels: int = 1
    block_size: int = 1280
    output_volume: float = 1.0  # linear gain applied to playback (0.0-1.0+)


class RecorderConfig(BaseModel):
    # WebRTC VAD end-of-utterance tuning; sensitive to mic and room.
    aggressiveness: int = 2  # VAD speech/silence sensitivity (0-3)
    silence_ms: int = 800  # trailing silence that ends an utterance
    max_ms: int = 10000  # hard cap on utterance length
    start_timeout_ms: int = 3000  # give up if no speech starts after wake
    preroll_frames: int = 6  # frames kept before wake, recovering a clipped command


class WakeConfig(BaseModel):
    model_path: str | None = None
    model_paths: list[str] | None = None  # load a series of models (any wakes)
    model_name: str = "hey_jarvis"
    threshold: float = 0.5

    def model_refs(self) -> list[str]:
        """Models to load, most specific first: a series, else a single path,
        else the stock bootstrap name."""
        if self.model_paths:
            return self.model_paths
        return [self.model_path] if self.model_path else [self.model_name]

    def phrases(self) -> list[str]:
        """The acceptable wake phrases, derived from the loaded models."""
        return phrases_for(self.model_refs())


class SttConfig(BaseModel):
    model: str = "base.en"
    compute_type: str = "int8"
    language: str = "en"
    beam_size: int = 5  # 1 = greedy; higher trades latency for accuracy
    vad_filter: bool = True  # strip non-speech/silence before decode
    condition_on_previous_text: bool = False  # commands are independent one-shots
    initial_prompt: str | None = None  # optional vocabulary/spelling bias


class LlmConfig(BaseModel):
    provider: str = "ollama"
    model: str = "qwen2.5:3b-instruct"
    host: str = "http://localhost:11434"
    timeout: float = 60.0
    health_timeout: float = 5.0  # separate, shorter timeout for the health check
    # Command the monitor TUI runs to (re)start the LLM server. Default manages a
    # local `ollama serve` as a child (no sudo); systemd users can point it at
    # e.g. ["systemctl", "--user", "restart", "ollama"].
    serve_cmd: list[str] = ["ollama", "serve"]
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


class SchedulingConfig(BaseModel):
    poll_seconds: float = 1.0  # how often the scheduler checks for due reminders


class WebSearchConfig(BaseModel):
    provider: str = "ddgs"
    result_count: int = 3
    timeout: float = 10.0
    region: str = "wt-wt"  # ddgs region; wt-wt = no region
    timelimit: str = "d"  # ddgs recency window: d/w/m/y; bias toward fresh results
    max_snippet_chars: int = 500  # truncate each result body (latency + injection surface)
    # Optional keyed accelerator. When set, app.py uses Tavily (live answer box) with
    # the keyless ddgs scraper as fallback. Usually supplied via
    # ASSISTANT_WEB_SEARCH__API_KEY rather than committed to config.yaml.
    api_key: str = ""
    tavily_endpoint: str = "https://api.tavily.com/search"


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
    recorder: RecorderConfig = RecorderConfig()
    wake: WakeConfig = WakeConfig()
    stt: SttConfig = SttConfig()
    llm: LlmConfig = LlmConfig()
    tts: TtsConfig = TtsConfig()
    storage: StorageConfig = StorageConfig()
    scheduling: SchedulingConfig = SchedulingConfig()
    web_search: WebSearchConfig = WebSearchConfig()
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
