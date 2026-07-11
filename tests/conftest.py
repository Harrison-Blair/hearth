"""Shared fixtures for FTHR-002 spine tests."""
from __future__ import annotations

import httpx
import pytest

from hearth.config import LLMBackend, LLMConfig, LLMTiers


def make_local_backend_config(**overrides) -> LLMBackend:
    defaults = dict(
        base_url="http://localhost:11434/v1",
        model="qwen3:14b",
        api_key_env=None,
        supports_tools=True,
        supports_streaming=True,
        context_window=8192,
        cost_tier="free",
        enabled=True,
    )
    defaults.update(overrides)
    return LLMBackend(**defaults)


@pytest.fixture
def llm_config() -> LLMConfig:
    return LLMConfig(
        backends={"local": make_local_backend_config()},
        tiers=LLMTiers(default="local", tool="local"),
        timeout=60.0,
        max_retries=2,
    )


@pytest.fixture
def canned_completion():
    def _make(text: str = "hello there", tool_calls=None, finish_reason: str = "stop") -> dict:
        message: dict = {"role": "assistant", "content": text}
        if tool_calls:
            message["tool_calls"] = tool_calls
        return {"choices": [{"message": message, "finish_reason": finish_reason}]}

    return _make


def make_mock_client(handler, base_url: str) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url=base_url)
