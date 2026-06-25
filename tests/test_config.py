from pathlib import Path

from assistant.core.config import Config


def test_loads_yaml_defaults():
    cfg = Config(_yaml_file=str(Path(__file__).parent.parent / "config.yaml"))
    assert cfg.wake.phrase == "hey assistant"
    assert cfg.stt.model == "base.en"
    assert cfg.audio.sample_rate == 16000


def test_env_override(monkeypatch):
    monkeypatch.setenv("ASSISTANT_LLM__MODEL", "llama3.2:3b")
    cfg = Config(_yaml_file=str(Path(__file__).parent.parent / "config.yaml"))
    assert cfg.llm.model == "llama3.2:3b"


def test_defaults_without_yaml():
    # Pointing at a nonexistent file should still yield model defaults.
    cfg = Config(_yaml_file="/nonexistent/config.yaml")
    assert cfg.wake.threshold == 0.5
    assert cfg.llm.provider == "ollama"
