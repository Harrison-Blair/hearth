from assistant.core.config import Config, LlmConfig, WakeConfig


def test_model_defaults():
    # Defaults live on the sub-models, independent of config.yaml.
    assert WakeConfig().threshold == 0.5
    assert LlmConfig().provider == "ollama"


def test_loads_yaml_and_overrides_defaults():
    # Config() reads config.yaml from the repo root (pytest cwd).
    cfg = Config()
    assert cfg.wake.phrase == "hey assistant"
    assert cfg.stt.model == "base.en"
    assert cfg.audio.sample_rate == 16000
    assert cfg.wake.threshold == 0.6  # config.yaml overrides the 0.5 default
    assert cfg.recorder.silence_ms == 800
    assert cfg.stt.beam_size == 1
    assert cfg.llm.health_timeout == 5.0


def test_env_override(monkeypatch):
    monkeypatch.setenv("ASSISTANT_LLM__MODEL", "llama3.2:3b")
    assert Config().llm.model == "llama3.2:3b"


def test_recorder_env_override(monkeypatch):
    monkeypatch.setenv("ASSISTANT_RECORDER__SILENCE_MS", "400")
    assert Config().recorder.silence_ms == 400
