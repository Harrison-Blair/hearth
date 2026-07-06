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
    normalize: bool = False  # peak-normalize the utterance before STT
    normalize_target_peak: float = 0.97  # target peak as fraction of full scale
    normalize_rms_floor: float = 200.0  # skip normalize below this int16 RMS (noise gate)
    # Captures quieter than this int16 RMS are treated as silence and never sent to
    # STT (whisper hallucinates text on near-silent audio). 0.0 = disabled.
    min_transcribe_rms: float = 0.0


class RecorderConfig(BaseModel):
    # WebRTC VAD end-of-utterance tuning; sensitive to mic and room.
    aggressiveness: int = 2  # VAD speech/silence sensitivity (0-3)
    silence_ms: int = 1500  # trailing silence that ends an utterance (forgiving of mid-command pauses)
    max_ms: int = 10000  # hard cap on utterance length
    start_timeout_ms: int = 5000  # give up if no speech starts after wake
    preroll_frames: int = 6  # frames kept before wake, recovering a clipped command


class WakeConfig(BaseModel):
    model_path: str | None = None
    model_paths: list[str] | None = None  # load a series of models (any wakes)
    model_name: str = "models/wake/calcifer.onnx"
    # Global across models; set from the manifest's per-model optimal threshold
    # after training (per-model thresholds deliberately not built).
    threshold: float = 0.66
    # Score every Nth 80ms frame once the ~2s window is full; raise to 2-4 on the
    # Pi 5 to cut CPU (stateless predict recomputes the full window per call) at
    # <= N*80ms extra latency.
    score_interval: int = 1
    # Consecutive scored frames over threshold required to fire; >1 debounces a
    # single noisy frame from spuriously waking the assistant. 1 = original trigger.
    trigger_frames: int = 1

    def model_refs(self) -> list[str]:
        """Models to load, most specific first: a series, else a single path,
        else the bundled default "hey assistant" model."""
        if self.model_paths:
            return self.model_paths
        return [self.model_path] if self.model_path else [self.model_name]

    def phrases(self) -> list[str]:
        """The acceptable wake phrases, derived from the loaded models."""
        return phrases_for(self.model_refs())


class SttConfig(BaseModel):
    model: str = "base.en"
    device: str = "cpu"  # ctranslate2 device: "cpu" or "cuda" (GPU deployments)
    compute_type: str = "int8"
    cpu_threads: int = 0  # 0 = ctranslate2 auto; pin to core count on the Pi
    language: str = "en"
    beam_size: int = 5  # 1 = greedy; higher trades latency for accuracy
    # Silero VAD inside whisper. Default off: the recorder already endpoints the
    # utterance, and a second VAD re-clips it and can drop the leading word.
    vad_filter: bool = False  # strip non-speech/silence before decode
    condition_on_previous_text: bool = False  # commands are independent one-shots
    initial_prompt: str | None = None  # optional vocabulary/spelling bias


class LlmConfig(BaseModel):
    provider: str = "ollama"
    model: str = "qwen2.5:3b-instruct"
    host: str = "http://localhost:11434"
    timeout: float = 60.0
    health_timeout: float = 5.0  # separate, shorter timeout for the health check
    num_ctx: int = 8192  # context window passed to Ollama (options.num_ctx)
    # qwen3 and other "thinking" models emit reasoning that bloats voice latency;
    # keep it off on the chat paths. No-op for models without a thinking mode.
    think: bool = False
    # Command the monitor TUI runs to (re)start the LLM server. Default manages a
    # local `ollama serve` as a child (no sudo); systemd users can point it at
    # e.g. ["systemctl", "--user", "restart", "ollama"].
    serve_cmd: list[str] = ["ollama", "serve"]
    # Answers are spoken aloud, so steer the model toward short, plain replies.
    system_prompt: str = (
        "You are a helpful voice assistant. Answers are read aloud, so reply in "
        "one or two short, plain sentences. No markdown, lists, or emoji."
    )


class NluConfig(BaseModel):
    command_keyphrase: str = "tool"
    command_aliases: dict[str, str] = {}


class AgentConfig(BaseModel):
    # How the orchestrator picks a tool: "native" = Ollama tool-calling only,
    # "json" = prompt-coerced JSON only, "auto" = native then JSON on failure.
    tool_mode: str = "auto"
    max_tool_rounds: int = 3  # safety cap on tool-call rounds before answering directly
    fast_path: bool = True  # LLM-free keyphrase/command shortcut for cheap commands
    turn_timeout_s: float = 20.0  # whole-turn budget; on expiry, answer from general knowledge


class TtsConfig(BaseModel):
    voice: str = "en_US-lessac-medium"
    model_path: str | None = None
    # Piper speaking rate (length_scale): >1 slower, <1 faster; None = voice default.
    length_scale: float | None = None
    # Pool of wake-acknowledgement phrases; one is chosen at random per wake. Kept
    # to espeak-friendly interjections so Piper says a natural cue rather than
    # spelling the letters (e.g. "Mm-hm" -> "em-em-aitch-em").
    ack_phrases: list[str] = ["hmm?", "uh huh?", "hmm hmm?"]


class StorageConfig(BaseModel):
    db_path: str = "assistant.db"


class SchedulingConfig(BaseModel):
    poll_seconds: float = 1.0  # how often the scheduler checks for due reminders


class WebSearchConfig(BaseModel):
    providers: list[str] = ["ddgs", "wikipedia"]  # fan-out set; order = merge priority
    language: str = "en"  # Wikipedia language variant (e.g. en, de, fr)
    region: str = "us-en"  # DuckDuckGo region
    result_count: int = 3  # results fetched per provider
    max_results: int = 5  # merged results cap fed to the LLM
    timeout: float = 10.0
    max_snippet_chars: int = 500  # truncate each result body (latency + injection surface)
    max_rounds: int = 2  # agentic search rounds before giving up
    progress_updates: bool = True  # speak "searching..." style updates mid-turn


class WeatherConfig(BaseModel):
    latitude: float = 33.749  # home: Atlanta, GA
    longitude: float = -84.38798
    location_name: str = "Atlanta"  # spoken label for "here"
    timezone: str = "auto"  # IANA tz or "auto" (resolve from coordinates)
    temperature_unit: str = "fahrenheit"  # fahrenheit | celsius
    wind_speed_unit: str = "mph"  # mph | kmh | ms | kn
    precipitation_unit: str = "inch"  # inch | mm
    forecast_days: int = 16  # days of daily outlook (Open-Meteo max is 16)
    timeout: float = 10.0
    forecast_endpoint: str = "https://api.open-meteo.com/v1/forecast"
    geocoding_endpoint: str = "https://geocoding-api.open-meteo.com/v1/search"


class ConversationConfig(BaseModel):
    enabled: bool = True  # keep listening for follow-ups after the assistant speaks
    followup_window_ms: int = 6000  # silence after which a conversation closes
    max_history_turns: int = 12  # messages kept in-session (user + assistant each 1)


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
    nlu: NluConfig = NluConfig()
    agent: AgentConfig = AgentConfig()
    tts: TtsConfig = TtsConfig()
    storage: StorageConfig = StorageConfig()
    scheduling: SchedulingConfig = SchedulingConfig()
    web_search: WebSearchConfig = WebSearchConfig()
    weather: WeatherConfig = WeatherConfig()
    conversation: ConversationConfig = ConversationConfig()
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
