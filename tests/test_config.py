from assistant.core.config import (
    AudioConfig,
    Config,
    ConversationConfig,
    LlmConfig,
    SttConfig,
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


def test_stt_device_env_override(monkeypatch):
    monkeypatch.setenv("ASSISTANT_STT__DEVICE", "cuda")
    assert Config().stt.device == "cuda"


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
    assert cfg.stt.model == "distil-small.en"
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
