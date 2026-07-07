from assistant.core.config import (
    AecConfig,
    AgentConfig,
    AudioConfig,
    BargeInConfig,
    Config,
    ConversationConfig,
    LlmConfig,
    LoggingConfig,
    RecorderConfig,
    SttConfig,
    TtsConfig,
    VerifyConfig,
    WakeConfig,
    WebSearchConfig,
)


def test_model_defaults():
    # Defaults live on the sub-models, independent of config.yaml.
    assert WakeConfig().threshold == 0.66
    assert LlmConfig().provider == "ollama"
    assert WebSearchConfig().language == "en"
    assert WebSearchConfig().result_count == 3
    assert SttConfig().device == "cpu"  # GPU boxes override via stt.device
    assert SttConfig().cpu_threads == 0  # 0 = ctranslate2 auto; the Pi pins this
    assert AudioConfig().normalize is False  # opt-in pre-STT peak normalization
    assert LoggingConfig().dir == "logs"
    assert LoggingConfig().file_enabled is True
    assert LoggingConfig().file_level == "INFO"
    assert LoggingConfig().runs_to_keep == 20


def test_stt_device_env_override(monkeypatch):
    monkeypatch.setenv("ASSISTANT_STT__DEVICE", "cuda")
    assert Config().stt.device == "cuda"


def test_wake_ack_confidence_defaults():
    # Confident wakes greet; low-score wakes (between threshold and
    # confident_threshold) signal an uncertain pickup.
    assert WakeConfig().confident_threshold == 0.85
    assert TtsConfig().ack_phrases == ["Hello!", "What can I help you with?", "Yes?"]
    assert TtsConfig().unsure_ack_phrases == ["Did you say something?", "What was that?"]
    cfg = Config()  # both mirrored in config.yaml
    assert cfg.wake.confident_threshold == 0.85
    assert cfg.tts.unsure_ack_phrases == ["Did you say something?", "What was that?"]


def test_wake_confident_threshold_env_override(monkeypatch):
    monkeypatch.setenv("ASSISTANT_WAKE__CONFIDENT_THRESHOLD", "0.9")
    assert Config().wake.confident_threshold == 0.9


def test_wake_model_refs_precedence():
    # Default model when nothing is configured.
    assert WakeConfig().model_refs() == ["models/wake/calcifer.onnx"]
    # A single custom path wins over the default.
    assert WakeConfig(model_path="a.onnx").model_refs() == ["a.onnx"]
    # A series wins over everything (the multi-phrase case).
    cfg = WakeConfig(model_path="a.onnx", model_paths=["a.onnx", "b.onnx"])
    assert cfg.model_refs() == ["a.onnx", "b.onnx"]


def test_wake_model_paths_env_override(monkeypatch):
    monkeypatch.setenv("ASSISTANT_WAKE__MODEL_PATHS", '["x.onnx", "y.onnx"]')
    assert Config().wake.model_refs() == ["x.onnx", "y.onnx"]


def test_web_search_config_loads():
    cfg = Config()
    assert cfg.web_search.providers == ["ddgs", "wikipedia"]
    assert cfg.web_search.language == "en"
    assert cfg.web_search.region == "us-en"
    assert cfg.web_search.result_count == 3
    assert cfg.web_search.max_results == 5
    assert cfg.web_search.max_snippet_chars == 500
    assert cfg.web_search.max_rounds == 2
    assert cfg.web_search.progress_updates is True


def test_web_search_env_override(monkeypatch):
    monkeypatch.setenv("ASSISTANT_WEB_SEARCH__RESULT_COUNT", "5")
    assert Config().web_search.result_count == 5


def test_weather_env_override(monkeypatch):
    monkeypatch.setenv("ASSISTANT_WEATHER__LATITUDE", "40.7")
    assert Config().weather.latitude == 40.7


def test_conversation_defaults():
    assert ConversationConfig().enabled is True
    assert ConversationConfig().followup_window_ms == 6000
    assert ConversationConfig().max_history_turns == 12
    assert ConversationConfig().decision_enabled is True
    assert "no" in ConversationConfig().decline_phrases


def test_silence_hardening_defaults():
    assert RecorderConfig().min_speech_ms == 150
    assert SttConfig().no_speech_threshold == 0.6
    assert SttConfig().log_prob_threshold == -1.0
    assert SttConfig().hallucination_max_rms == 300.0
    assert "thank you" in SttConfig().hallucination_phrases


def test_decision_enabled_env_override(monkeypatch):
    monkeypatch.setenv("ASSISTANT_CONVERSATION__DECISION_ENABLED", "false")
    assert Config().conversation.decision_enabled is False


def test_min_speech_ms_env_override(monkeypatch):
    monkeypatch.setenv("ASSISTANT_RECORDER__MIN_SPEECH_MS", "60")
    assert Config().recorder.min_speech_ms == 60


def test_aec_defaults():
    assert AecConfig().enabled is False
    assert AecConfig().frame_ms == 20
    assert AecConfig().filter_length_ms == 200
    assert AecConfig().extra_delay_ms == 0


def test_barge_in_defaults():
    assert BargeInConfig().enabled is False  # off until AEC is validated on-device
    assert BargeInConfig().threshold == 0.80
    assert BargeInConfig().trigger_frames == 3
    assert BargeInConfig().announcements is False


def test_barge_in_env_override(monkeypatch):
    monkeypatch.setenv("ASSISTANT_BARGE_IN__ENABLED", "true")
    monkeypatch.setenv("ASSISTANT_BARGE_IN__THRESHOLD", "0.9")
    config = Config()
    assert config.barge_in.enabled is True
    assert config.barge_in.threshold == 0.9


def test_conversation_config_loads():
    cfg = Config()
    assert cfg.conversation.enabled is True
    assert cfg.conversation.followup_window_ms == 6000
    assert cfg.conversation.max_history_turns == 12


def test_conversation_env_override(monkeypatch):
    monkeypatch.setenv("ASSISTANT_CONVERSATION__FOLLOWUP_WINDOW_MS", "2000")
    assert Config().conversation.followup_window_ms == 2000


def test_loads_yaml_and_overrides_defaults():
    # Config() reads config.yaml from the repo root (pytest cwd).
    cfg = Config()
    assert cfg.stt.model == "medium"
    assert cfg.stt.cpu_threads == 4  # pinned to the Pi 5's core count
    assert cfg.audio.sample_rate == 16000
    assert cfg.audio.normalize is True
    assert cfg.wake.threshold == 0.66  # manifest-optimal trained threshold
    assert cfg.recorder.silence_ms == 1500
    assert cfg.stt.beam_size == 5
    assert cfg.stt.vad_filter is False  # recorder already endpoints; avoid double-VAD clipping
    assert cfg.stt.condition_on_previous_text is False
    assert cfg.llm.health_timeout == 5.0


def test_env_override(monkeypatch):
    monkeypatch.setenv("ASSISTANT_LLM__MODEL", "llama3.2:3b")
    assert Config().llm.model == "llama3.2:3b"


def test_recorder_env_override(monkeypatch):
    monkeypatch.setenv("ASSISTANT_RECORDER__SILENCE_MS", "400")
    assert Config().recorder.silence_ms == 400


def test_stt_cpu_threads_env_override(monkeypatch):
    monkeypatch.setenv("ASSISTANT_STT__CPU_THREADS", "2")
    assert Config().stt.cpu_threads == 2


def test_audio_normalize_env_override(monkeypatch):
    monkeypatch.setenv("ASSISTANT_AUDIO__NORMALIZE", "false")
    assert Config().audio.normalize is False


def test_verify_defaults():
    v = VerifyConfig()
    assert v.enabled is True
    assert v.pre is True
    assert v.post is True
    assert v.max_verify_rounds == 2
    assert v.spoken_feedback is True


def test_verify_env_override(monkeypatch):
    monkeypatch.setenv("ASSISTANT_VERIFY__ENABLED", "false")
    monkeypatch.setenv("ASSISTANT_VERIFY__SPOKEN_FEEDBACK", "false")
    monkeypatch.setenv("ASSISTANT_VERIFY__MAX_VERIFY_ROUNDS", "3")
    cfg = Config()
    assert cfg.verify.enabled is False
    assert cfg.verify.spoken_feedback is False
    assert cfg.verify.max_verify_rounds == 3


def test_verify_loads_from_yaml():
    # config.yaml carries the verify block; Config() surfaces it.
    cfg = Config()
    assert cfg.verify.enabled is True
    assert cfg.verify.pre is True
    assert cfg.verify.post is True
    assert cfg.verify.spoken_feedback is True
    assert cfg.verify.max_verify_rounds == 2


def test_raised_turn_and_utterance_defaults():
    # The verify loop needs a longer turn budget and utterance cap than the
    # original single-pass voice turn.
    assert RecorderConfig().max_ms == 30000
    assert AgentConfig().turn_timeout_s == 45.0


def test_recorder_max_ms_env_override(monkeypatch):
    monkeypatch.setenv("ASSISTANT_RECORDER__MAX_MS", "12000")
    assert Config().recorder.max_ms == 12000


def test_agent_turn_timeout_env_override(monkeypatch):
    monkeypatch.setenv("ASSISTANT_AGENT__TURN_TIMEOUT_S", "60")
    assert Config().agent.turn_timeout_s == 60.0


def test_llm_max_retries_default_and_override(monkeypatch):
    assert LlmConfig().max_retries == 2
    monkeypatch.setenv("ASSISTANT_LLM__MAX_RETRIES", "0")
    assert Config().llm.max_retries == 0
