"""Streaming LLM interface and its OpenAI-compatible adapter."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from typing import Protocol, cast

from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionMessageParam

from .config import BackendConfig, api_key_for
from .history import ChatMessage


class LLMClient(Protocol):
    """A streaming chat completion client."""

    def stream(self, messages: Sequence[ChatMessage]) -> AsyncIterator[str]:
        """Yield text pieces of the assistant reply."""
        ...

    async def aclose(self) -> None:
        """Release the underlying HTTP client."""
        ...


class OpenAILLMClient:
    """Adapter for any OpenAI-compatible chat completions endpoint."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        timeout_s: float,
    ) -> None:
        self._client = AsyncOpenAI(base_url=base_url, api_key=api_key, timeout=timeout_s)
        self._model = model

    async def stream(self, messages: Sequence[ChatMessage]) -> AsyncIterator[str]:
        request_messages = cast(
            "list[ChatCompletionMessageParam]",
            [{"role": message["role"], "content": message["content"]} for message in messages],
        )
        stream = await self._client.chat.completions.create(
            model=self._model,
            messages=request_messages,
            stream=True,
        )
        try:
            async for chunk in stream:
                if not chunk.choices:
                    continue
                content = chunk.choices[0].delta.content
                if content:
                    yield content
        finally:
            await stream.close()

    async def aclose(self) -> None:
        await self._client.close()


def build_llm(config: BackendConfig, role: str = "fast") -> LLMClient:
    """Build the client for one configured role."""
    role_config = config.roles[role]
    provider = config.providers[role_config.provider]
    return OpenAILLMClient(
        base_url=provider.base_url,
        api_key=api_key_for(config, role),
        model=role_config.model,
        timeout_s=config.llm.timeout_s,
    )
