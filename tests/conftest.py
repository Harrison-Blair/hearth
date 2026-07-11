"""Shared fixtures for FTHR-002 spine tests."""
from __future__ import annotations

import logging
from typing import Callable

import httpx
import pytest

from hearth.config import LLMBackend, LLMConfig, LLMTiers


@pytest.fixture(autouse=True)
def _reset_logging_state():
    """`hearth.logging_setup.setup_logging` (FTHR-011) mutates the process-
    global root/`websockets` loggers; any test exercising it (directly, or
    via `_run_daemon`) would otherwise leak a handler bound to one test's
    tmp_path into every later test in the session. Isolate each test."""
    root = logging.getLogger()
    ws_logger = logging.getLogger("websockets")
    orig_root_handlers = root.handlers[:]
    orig_root_level = root.level
    orig_ws_handlers = ws_logger.handlers[:]
    orig_marker = root.__dict__.get("_hearth_logging_configured")

    yield

    for handler in root.handlers[:]:
        if handler not in orig_root_handlers:
            root.removeHandler(handler)
            handler.close()
    root.setLevel(orig_root_level)
    if orig_marker is None:
        root.__dict__.pop("_hearth_logging_configured", None)
    else:
        root._hearth_logging_configured = orig_marker
    for handler in ws_logger.handlers[:]:
        if handler not in orig_ws_handlers:
            ws_logger.removeHandler(handler)


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
def two_tier_llm_config() -> LLMConfig:
    """A genuine local (`default`) / remote (`tool`) pair on distinct hosts,
    both enabled -- for tests exercising the orchestrator/consult_brain
    split (FTHR-009)."""
    return LLMConfig(
        backends={
            "local": LLMBackend(
                base_url="http://local-llm.test/v1",
                model="qwen3:14b",
                api_key_env=None,
                supports_tools=True,
                supports_streaming=True,
                context_window=8192,
                cost_tier="free",
                enabled=True,
            ),
            "remote": LLMBackend(
                base_url="https://remote-llm.test/v1",
                model="openrouter/free",
                api_key_env="HEARTH_LLM__OPENROUTER_API_KEY",
                supports_tools=True,
                supports_streaming=True,
                context_window=8192,
                cost_tier="free",
                enabled=True,
            ),
        },
        tiers=LLMTiers(default="local", tool="remote"),
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


class HostRouter:
    """A `httpx.MockTransport` handler that branches on `request.url.host`,
    with a per-host call counter -- lets multi-backend tests assert
    deterministically per host (local vs remote vs wiki) instead of relying
    on global request order."""

    def __init__(self, handlers: dict[str, Callable[[httpx.Request, int], httpx.Response]]):
        self._handlers = handlers
        self.counts: dict[str, int] = {host: 0 for host in handlers}

    def __call__(self, request: httpx.Request) -> httpx.Response:
        host = request.url.host
        handler = self._handlers.get(host)
        if handler is None:
            raise AssertionError(f"unexpected request host: {host!r}")
        self.counts[host] += 1
        return handler(request, self.counts[host])
