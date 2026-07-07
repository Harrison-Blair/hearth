"""Gateway-table resolution in ``app._build_one_llm`` — no network, unit only."""

from assistant.app import _build_one_llm
from assistant.core.config import LlmConfig
from assistant.llm.ollama_provider import OllamaProvider
from assistant.llm.openai_compatible_provider import GATEWAYS, OpenAICompatibleProvider


async def test_openrouter_resolves_to_openrouter_base_url():
    cfg = LlmConfig(provider="openrouter", api_key="k", base_url="")
    provider = _build_one_llm(cfg, "openrouter", cfg.model)
    assert isinstance(provider, OpenAICompatibleProvider)
    assert provider._base_url == GATEWAYS["openrouter"]["base_url"]
    await provider.aclose()


async def test_opencode_zen_resolves_to_zen_base_url():
    cfg = LlmConfig(provider="opencode-zen", api_key="k", base_url="")
    provider = _build_one_llm(cfg, "opencode-zen", cfg.model)
    assert isinstance(provider, OpenAICompatibleProvider)
    assert provider._base_url == GATEWAYS["opencode-zen"]["base_url"]
    await provider.aclose()


async def test_blank_base_url_uses_table_default():
    cfg = LlmConfig(provider="openrouter", api_key="k", base_url="")
    provider = _build_one_llm(cfg, "openrouter", cfg.model)
    assert provider._base_url == GATEWAYS["openrouter"]["base_url"].rstrip("/")
    await provider.aclose()


async def test_explicit_base_url_overrides_table_default():
    cfg = LlmConfig(provider="openrouter", api_key="k", base_url="https://example.com/v1")
    provider = _build_one_llm(cfg, "openrouter", cfg.model)
    assert provider._base_url == "https://example.com/v1"
    await provider.aclose()


async def test_unknown_provider_falls_back_to_ollama():
    cfg = LlmConfig(provider="nonsense")
    provider = _build_one_llm(cfg, "nonsense", cfg.model)
    assert isinstance(provider, OllamaProvider)
