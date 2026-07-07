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
    max_ms: int = 30000  # hard cap; long enough for multi-clause utterances + the verify loop
    start_timeout_ms: int = 5000  # give up if no speech starts after wake
    # Cumulative voiced ms before a capture counts as speech; rejects one-frame
    # VAD blips (a chair creak) that would otherwise open an utterance. Keep low
    # enough that a bare "no" still registers.
    min_speech_ms: int = 150
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
    # Scores at/above this speak a confident acknowledgement (tts.ack_phrases);
    # between `threshold` and this, an unsure one (tts.unsure_ack_phrases).
    confident_threshold: float = 0.85

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
    # Segments whose no-speech probability exceeds this are dropped (whisper's own
    # skip additionally requires a low avg logprob, which confident hallucinations
    # dodge). Lower = stricter silence rejection.
    no_speech_threshold: float = 0.6
    log_prob_threshold: float = -1.0  # discard decodes with avg logprob below this
    # Known whisper hallucinations on (near-)silent audio. A low-energy capture
    # whose whole transcript is only these phrases is treated as silence.
    hallucination_phrases: list[str] = [
        "thank you",
        "thanks for watching",
        "thank you for watching",
        "thank you so much for watching",
        "please subscribe",
        "subscribe to my channel",
        "see you next time",
        "see you in the next video",
        "bye",
        "bye bye",
        "you",
    ]
    # The phrase filter only applies to captures quieter than this raw int16 RMS
    # (real speech is louder and passes through untouched). 0 = filter off.
    hallucination_max_rms: float = 300.0


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
    # OpenAI-compatible gateway providers (provider: "opencode-zen" |
    # "openrouter"). The bearer token is read from the ASSISTANT_LLM__API_KEY env
    # var — never commit it to config.yaml. base_url blank uses that provider's
    # gateway default (see llm/openai_compatible_provider.py:GATEWAYS); any
    # OpenAI-compatible endpoint can be set explicitly to override it.
    api_key: str = ""
    base_url: str = ""
    # Secondary provider used when the primary raises (transport failure,
    # timeout, malformed response). Empty = no fallback. ``fallback_model``
    # defaults to ``model`` when blank, so the same model id can serve both.
    fallback: str = ""
    fallback_model: str = ""
    # Retries on transient (429/5xx/transport, malformed 200 body) LLM failures.
    # 4xx-auth is never retried. Advanced — config.yaml only, not in the TUI.
    max_retries: int = 2
    # Answers are spoken aloud, so steer the model toward short, plain replies.
    system_prompt: str = (
        "You are a helpful voice assistant. Answers are read aloud, so reply in "
        "one or two short, plain sentences. No markdown, lists, or emoji. Lead "
        "directly with the answer — never start with acknowledgements, preambles, "
        "or a restatement of the question (no 'Sure', 'Okay', 'Great question', "
        "'Here's')."
    )


class PersonaConfig(BaseModel):
    # On by default: the Calcifer voice on final spoken replies (general answers,
    # weather, web-search summaries) only — never tool selection, argument
    # formatting, or JSON structured output. Set false for the plain voice.
    enabled: bool = True
    strength: str = "terse"  # terse | expansive
    # Live-restyle a plain (non-persona'd) skill reply in the persona's voice at
    # the pipeline's speak choke point (core/revoice.py:Revoicer). False = plain
    # replies stay plain even with persona enabled.
    revoice_enabled: bool = True
    revoice_timeout_s: float = 5.0  # bounds the live revoice LLM call


class AgentConfig(BaseModel):
    # How the orchestrator picks a tool: "native" = Ollama tool-calling only,
    # "json" = prompt-coerced JSON only, "auto" = native then JSON on failure.
    tool_mode: str = "auto"
    max_tool_rounds: int = 3  # safety cap on tool-call rounds before answering directly
    turn_timeout_s: float = 45.0  # whole-turn budget; fits the verify loop + one reject re-loop


class VerifyConfig(BaseModel):
    # Follow-up verification loop: an LLM "assess" call reviews the model's tool
    # pick (pre-stage) and its drafted answer (post-stage) before speech, with
    # optional spoken fillers ("let me double check that") on a reject. Off =
    # today's single-pass behavior. The judgment prompt is a hard-coded constant
    # in verify.py (not a config field) — it encodes the safety structure.
    enabled: bool = True          # master kill switch; off = today's behavior
    pre: bool = True              # pre-tool gate: review pick+args before the skill runs
    post: bool = True             # post-tool check: review the answer before speech
    max_verify_rounds: int = 2    # per-stage sub-cap (rejects) within max_tool_rounds
    spoken_feedback: bool = True  # speak "let me double check" fillers on a reject


class TtsConfig(BaseModel):
    voice: str = "en_US-lessac-medium"
    model_path: str | None = None
    # Piper speaking rate (length_scale): >1 slower, <1 faster; None = voice default.
    length_scale: float | None = None
    # Pool of wake-acknowledgement phrases; one is chosen at random per wake.
    # Spoken when the wake score is at/above wake.confident_threshold.
    ack_phrases: list[str] = ["Hello!", "What can I help you with?", "Yes?"]
    # Spoken instead when the wake score lands between wake.threshold and
    # wake.confident_threshold, signalling the pickup was uncertain.
    unsure_ack_phrases: list[str] = ["Did you say something?", "What was that?"]
    # Beat of silence before the wake ack plays, so "hmm?" isn't instant/robotic. 0 = off.
    ack_delay_s: float = 0.3


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
    # AI-first providers (keyed). Empty = disabled, keyless-only fan-out above.
    # Real keys arrive only via ASSISTANT_WEB_SEARCH__TAVILY_API_KEY / __EXA_API_KEY.
    tavily_api_key: str = ""
    tavily_endpoint: str = "https://api.tavily.com/search"
    exa_api_key: str = ""


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


class CalendarConfig(BaseModel):
    enabled: bool = False  # gates skill registration and the watcher entirely
    # Google service-account JSON; ~ is expanded where the file is read.
    credentials_path: str = "~/.config/calcifer/google-service-account.json"
    personal_calendar_id: str = ""  # read-only for the service account
    calcifer_calendar_id: str = ""  # read-write; events Calcifer creates live here
    timeout: float = 10.0
    watcher_enabled: bool = True  # watcher's state at boot; voice toggle overrides at runtime
    watcher_poll_seconds: float = 300.0  # how often the watcher polls the calendars
    watcher_lead_minutes: int = 15  # announce events starting within this window
    # Title patterns never surfaced in queries or announcements (substring,
    # case/emoji-insensitive); the "stop bringing up ..." voice command adds more.
    blocked_titles: list[str] = []
    # Events whose description contains this marker are hidden the same way.
    hidden_tag: str = "[hidden]"


class ConversationConfig(BaseModel):
    enabled: bool = True  # keep listening for follow-ups after the assistant speaks
    followup_window_ms: int = 6000  # silence after which a conversation closes
    max_history_turns: int = 12  # messages kept in-session (user + assistant each 1)
    # After each completed reply the LLM decides what happens next: keep
    # listening silently (the reply asked a question), check in once (a soft
    # ready-tone at mic-open — at most once per conversation), or end the
    # conversation. Nothing is ever spoken at a conversation boundary. Decided
    # while the reply is spoken so it adds no mic-open latency; falls back to a
    # silent reopen (the silence-closed loop) if the LLM misses the budget or
    # is offline.
    decision_enabled: bool = True
    decision_timeout_s: float = 4.0  # decision must land by mic-open or it's dropped
    decision_prompt: str = (
        "You decide what a voice assistant does right after speaking its reply. "
        "Read the conversation and reply with ONLY a JSON object: "
        '{"action": "listen" | "confirm" | "end"}. '
        "Choose listen when the assistant's last reply asks the user a question "
        "or clearly expects an answer. "
        "Choose confirm when the request was completed and no answer is expected "
        "but a follow-up is plausible (a brief ready-tone will play). "
        "Choose end when the conversation is clearly over (the user was wrapping "
        "up or declining more help). "
        "When unsure, choose listen."
    )
    # Follow-ups that decline the check-in tone and end the conversation.
    # Matched exactly against the normalized transcript, and only on the turn
    # right after a check-in.
    decline_phrases: list[str] = [
        "no",
        "nope",
        "nah",
        "no thanks",
        "no thank you",
        "nothing",
        "nothing else",
        "that's it",
        "that is it",
        "i'm good",
        "i am good",
        "all good",
        "we're good",
        "we are good",
    ]
    # Follow-up utterances that explicitly close the conversation (matched as a
    # normalized substring). A match ends the turn without routing to a skill —
    # the descending mic-close tone is the only acknowledgment.
    end_phrases: list[str] = [
        "goodbye",
        "bye",
        "that's all",
        "that is all",
        "i'm done",
        "i am done",
        "we're done",
        "we are done",
        "nevermind",
        "never mind",
    ]


class AecConfig(BaseModel):
    # Speex acoustic echo cancellation: subtracts what the speaker is playing
    # from the mic stream, so barge-in can hear the wake word over the
    # assistant's own voice. Needs the optional native extra:
    #   sudo apt install libspeexdsp-dev && pip install -e ".[aec]"
    # When disabled or the import fails, the mic passes through unchanged.
    enabled: bool = False
    frame_ms: int = 20  # speex processes 10-20 ms frames
    filter_length_ms: int = 200  # echo tail the canceller adapts over
    extra_delay_ms: int = 0  # output-path latency compensation; tune on-device


class BargeInConfig(BaseModel):
    # Speaking the wake word over the assistant's reply cuts playback and reopens
    # the mic. Off by default until echo cancellation is validated on-device:
    # without AEC the mic hears the assistant's own reply, and the gates below
    # are the only guard against self-triggering.
    enabled: bool = False
    # Extra score gate applied to wake events while we speak (>= wake.threshold).
    threshold: float = 0.80
    # Consecutive gated events required to barge (self-echo debounce).
    trigger_frames: int = 3
    # Also barge into reminder/calendar announcements (phase 3c).
    announcements: bool = False


class LoggingConfig(BaseModel):
    level: str = "INFO"  # console (stderr) level; the TUI parses that format
    dir: str = "logs"  # per-run log files land here (gitignored)
    file_enabled: bool = True  # write per-run plain-text + JSONL files
    file_level: str = "INFO"  # file handlers' level; set DEBUG when deep-debugging
    rotate_max_bytes: int = 10_485_760  # size cap per file within a run (10 MiB)
    rotate_backups: int = 3  # rotated chunks kept per file within a run
    runs_to_keep: int = 20  # runs retained at boot; older pruned (0 = keep all)


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
    persona: PersonaConfig = PersonaConfig()
    agent: AgentConfig = AgentConfig()
    verify: VerifyConfig = VerifyConfig()
    tts: TtsConfig = TtsConfig()
    storage: StorageConfig = StorageConfig()
    scheduling: SchedulingConfig = SchedulingConfig()
    web_search: WebSearchConfig = WebSearchConfig()
    weather: WeatherConfig = WeatherConfig()
    calendar: CalendarConfig = CalendarConfig()
    conversation: ConversationConfig = ConversationConfig()
    aec: AecConfig = AecConfig()
    barge_in: BargeInConfig = BargeInConfig()
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
