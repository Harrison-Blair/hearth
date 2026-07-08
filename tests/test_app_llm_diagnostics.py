"""Vendor-agnostic LLM boot diagnostics — pure helpers, no daemon boot, no network."""

from assistant.app import _gateway_base_url, _llm_unhealthy_warning
from assistant.core.config import LlmConfig
from assistant.llm.openai_compatible_provider import GATEWAYS


def test_gateway_base_url_openrouter():
    cfg = LlmConfig(provider="openrouter", base_url="")
    assert _gateway_base_url(cfg) == GATEWAYS["openrouter"]["base_url"]


def test_gateway_base_url_opencode_zen():
    cfg = LlmConfig(provider="opencode-zen", base_url="")
    assert _gateway_base_url(cfg) == GATEWAYS["opencode-zen"]["base_url"]


def test_gateway_base_url_explicit_override():
    cfg = LlmConfig(provider="openrouter", base_url="https://example.com/v1")
    assert _gateway_base_url(cfg) == "https://example.com/v1"


def test_gateway_base_url_ollama_is_none():
    cfg = LlmConfig(provider="ollama")
    assert _gateway_base_url(cfg) is None


def test_unhealthy_warning_openrouter_names_gateway():
    cfg = LlmConfig(provider="openrouter", base_url="", model="gpt-oss")
    msg = _llm_unhealthy_warning(cfg)
    assert "openrouter" in msg
    assert GATEWAYS["openrouter"]["base_url"] in msg
    assert "ASSISTANT_LLM__API_KEY" in msg


def test_unhealthy_warning_opencode_zen_names_gateway():
    cfg = LlmConfig(provider="opencode-zen", base_url="", model="gpt-oss")
    msg = _llm_unhealthy_warning(cfg)
    assert "opencode-zen" in msg
    assert GATEWAYS["opencode-zen"]["base_url"] in msg
    assert "ASSISTANT_LLM__API_KEY" in msg


def test_unhealthy_warning_ollama_gives_ollama_serve_message():
    cfg = LlmConfig(provider="ollama", host="http://localhost:11434", model="qwen2.5:3b-instruct")
    msg = _llm_unhealthy_warning(cfg)
    assert "ollama serve" in msg
    assert "openrouter" not in msg
