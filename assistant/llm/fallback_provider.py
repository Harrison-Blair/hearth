"""Primary-then-fallback LLM wrapper.

Holds two ``LLMProvider`` instances and delegates to the primary; on exception
(transport failure, timeout, malformed response) it retries on the fallback.
A valid-but-empty primary response does NOT fall back — the orchestrator already
handles empty ``ChatResponse``. The boundary is exception-based so a slow-but-
working primary is never preempted.
"""

from __future__ import annotations

import logging

from assistant.llm.base import ChatResponse, LLMProvider

log = logging.getLogger(__name__)


class FallbackLLMProvider(LLMProvider):
    def __init__(self, primary: LLMProvider, fallback: LLMProvider) -> None:
        self._primary = primary
        self._fallback = fallback

    async def aclose(self) -> None:
        await self._primary.aclose()
        await self._fallback.aclose()

    async def complete(
        self, prompt: str, *, system: str | None = None, json: bool = False, label: str = ""
    ) -> str:
        try:
            return await self._primary.complete(prompt, system=system, json=json, label=label)
        except Exception as exc:  # noqa: BLE001 - any primary failure is fallback-worthy
            log.warning("Primary LLM failed (%s); falling back for complete(%r)", exc, label)
            return await self._fallback.complete(prompt, system=system, json=json, label=label)

    async def chat(
        self, messages: list[dict], *, system: str | None = None, label: str = ""
    ) -> str:
        try:
            return await self._primary.chat(messages, system=system, label=label)
        except Exception as exc:  # noqa: BLE001
            log.warning("Primary LLM failed (%s); falling back for chat(%r)", exc, label)
            return await self._fallback.chat(messages, system=system, label=label)

    async def chat_tools(
        self,
        messages: list[dict],
        *,
        system: str | None = None,
        tools: list[dict] | None = None,
        label: str = "",
    ) -> ChatResponse:
        try:
            return await self._primary.chat_tools(
                messages, system=system, tools=tools, label=label
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("Primary LLM failed (%s); falling back for chat_tools(%r)", exc, label)
            return await self._fallback.chat_tools(
                messages, system=system, tools=tools, label=label
            )

    async def health(self) -> bool:
        primary_ok = await self._primary.health()
        fallback_ok = await self._fallback.health()
        if not primary_ok:
            log.warning("Primary LLM unhealthy; fallback will be used on failure.")
        if not fallback_ok:
            log.warning("Fallback LLM unhealthy; no safety net if primary fails.")
        return primary_ok or fallback_ok
