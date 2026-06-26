from assistant.core.config import Config, LlmConfig, WakeConfig, WebSearchConfig


def test_model_defaults():
    # Defaults live on the sub-models, independent of config.yaml.
    assert WakeConfig().threshold == 0.5
    assert LlmConfig().provider == "ollama"
    assert WebSearchConfig().provider == "ddgs"
    assert WebSearchConfig().result_count == 3


def test_wake_model_refs_precedence():
    # Bundled default model when nothing is configured.
    assert WakeConfig().model_refs() == ["models/wake/hey_assistant.onnx"]
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
    assert cfg.web_search.provider == "ddgs"
    assert cfg.web_search.region == "wt-wt"
    assert cfg.web_search.timelimit == "d"
    assert cfg.web_search.api_key == ""  # keyless by default


def test_web_search_env_override(monkeypatch):
    monkeypatch.setenv("ASSISTANT_WEB_SEARCH__RESULT_COUNT", "5")
    assert Config().web_search.result_count == 5


def test_loads_yaml_and_overrides_defaults():
    # Config() reads config.yaml from the repo root (pytest cwd).
    cfg = Config()
    assert cfg.wake.phrases() == ["hey assistant"]  # derived from the loaded model
    assert cfg.stt.model == "base.en"
    assert cfg.audio.sample_rate == 16000
    assert cfg.wake.threshold == 0.5  # tuned for fewer missed wakes
    assert cfg.recorder.silence_ms == 800
    assert cfg.stt.beam_size == 5
    assert cfg.stt.vad_filter is True
    assert cfg.stt.condition_on_previous_text is False
    assert cfg.llm.health_timeout == 5.0


def test_env_override(monkeypatch):
    monkeypatch.setenv("ASSISTANT_LLM__MODEL", "llama3.2:3b")
    assert Config().llm.model == "llama3.2:3b"


def test_recorder_env_override(monkeypatch):
    monkeypatch.setenv("ASSISTANT_RECORDER__SILENCE_MS", "400")
    assert Config().recorder.silence_ms == 400
