"""LLM completions via OpenCode Zen (OpenAI-compatible /chat/completions).

Same ``LLMProvider`` contract as ``OllamaProvider``; differs only in wire shape.
Models live server-side, so ``health`` just checks the gateway answers, not that
a specific model is pulled.
"""

from __future__ import annotations

import asyncio
import json as _json
import logging
import random
import time

import httpx

from assistant.core.events import ToolCall
from assistant.llm.base import ChatResponse, LLMProvider

log = logging.getLogger(__name__)


def _clip(s: str, n: int) -> str:
    return s if len(s) <= n else s[:n] + "…"


class LLMResponseError(Exception):
    """A reached-but-unusable LLM response: non-JSON body, empty choices, or a
    missing message. ``retryable`` flags transient gateway hiccups (a 200 with a
    truncated body) vs. auth/config bugs (400/401/403), which are non-retryable."""

    def __init__(self, message: str, *, retryable: bool) -> None:
        super().__init__(message)
        self.retryable = retryable


class OpenCodeZenProvider(LLMProvider):
    def __init__(
        self,
        model: str,
        api_key: str,
        base_url: str = "https://opencode.ai/zen/v1",
        timeout: float = 60.0,
        health_timeout: float = 5.0,
        max_retries: int = 2,
        retry_backoff_s: float = 0.5,
    ) -> None:
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._health_timeout = health_timeout
        # Retries on transient failures (429/5xx, transport errors, malformed 200
        # bodies). 4xx-auth (400/401/403) is never retried — it's a config bug.
        self._max_retries = max(0, max_retries)
        self._retry_backoff_s = retry_backoff_s
        # One pooled client reused across every call (a voice turn makes 2+);
        # a fresh client per request loses keep-alive entirely.
        self._client = httpx.AsyncClient(
            timeout=timeout,
            headers={"Authorization": f"Bearer {api_key}"},
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def complete(
        self, prompt: str, *, system: str | None = None, json: bool = False, label: str = ""
    ) -> str:
        msgs: list[dict] = []
        if system:
            msgs.append({"role": "system", "content": system})
        msgs.append({"role": "user", "content": prompt})
        payload: dict = {"model": self._model, "messages": msgs, "stream": False}
        if json:
            payload["response_format"] = {"type": "json_object"}

        latency_ms, data = await self._post(payload)
        response = (data["choices"][0]["message"].get("content") or "").strip()
        tag = label or "llm"
        log.info("[%s] prompt: %s", tag, _clip(prompt, 200))
        if system:
            log.info("[%s] system: %s", tag, _clip(system, 120))
        log.info(
            "[%s] response: %s", tag, _clip(response, 200),
            extra={"data": {
                "kind": "llm.complete", "label": tag, "model": self._model,
                "prompt": prompt, "system": system, "response": response,
                "json": json, "latency_ms": latency_ms,
            }},
        )
        return response

    async def chat(
        self, messages: list[dict], *, system: str | None = None, label: str = ""
    ) -> str:
        msgs = messages
        if system:
            msgs = [{"role": "system", "content": system}, *messages]
        payload = {"model": self._model, "messages": msgs, "stream": False}

        latency_ms, data = await self._post(payload)
        response = (data["choices"][0]["message"].get("content") or "").strip()
        tag = label or "llm"
        log.info("[%s] chat (%d msgs)", tag, len(msgs))
        log.info(
            "[%s] response: %s", tag, response,
            extra={"data": {
                "kind": "llm.chat", "label": tag, "model": self._model,
                "messages": msgs, "response": response, "latency_ms": latency_ms,
            }},
        )
        return response

    async def chat_tools(
        self,
        messages: list[dict],
        *,
        system: str | None = None,
        tools: list[dict] | None = None,
        label: str = "",
    ) -> ChatResponse:
        msgs = messages
        if system:
            msgs = [{"role": "system", "content": system}, *messages]
        payload: dict = {"model": self._model, "messages": msgs, "stream": False}
        if tools:
            payload["tools"] = tools

        latency_ms, data = await self._post(payload)
        message = data["choices"][0]["message"]
        content = (message.get("content") or "").strip()
        calls: list[ToolCall] = []
        for tc in message.get("tool_calls") or []:
            fn = tc.get("function", {})
            name = fn.get("name")
            if not name:
                continue
            args = fn.get("arguments")
            if isinstance(args, str):
                # OpenAI ships arguments as a JSON string, not an object.
                try:
                    args = _json.loads(args)
                except _json.JSONDecodeError:
                    args = {}
            calls.append(ToolCall(name=name, arguments=args if isinstance(args, dict) else {}))
        tag = label or "llm"
        log.info(
            "[%s] chat_tools (%d msgs, %d tools) -> %d call(s), content: %s",
            tag, len(msgs), len(tools or []), len(calls), _clip(content, 120),
            extra={"data": {
                "kind": "llm.chat_tools", "label": tag, "model": self._model,
                "messages": msgs,
                "tools": [t["function"]["name"] for t in tools or []],
                "content": content,
                "tool_calls": [{"name": c.name, "arguments": c.arguments} for c in calls],
                "latency_ms": latency_ms,
            }},
        )
        return ChatResponse(content=content, tool_calls=calls)

    async def health(self) -> bool:
        try:
            resp = await self._client.get(
                f"{self._base_url}/models", timeout=self._health_timeout
            )
            resp.raise_for_status()
        except (httpx.HTTPError, _json.JSONDecodeError) as exc:
            log.warning("OpenCode Zen health check failed: %s", exc)
            return False
        return True

    async def _post(self, payload: dict) -> tuple[int, dict]:
        """POST /chat/completions, retrying transient failures.

        Retries 429/5xx, transport/timeout errors, and retryable malformed 200
        bodies (non-JSON, empty choices, missing message). Never retries
        4xx-auth (400/401/403) — those are config bugs, and retrying only burns
        the budget. Raises ``LLMResponseError`` once retries are exhausted on a
        malformed body; ``HTTPStatusError`` propagates for a non-retryable or
        exhausted 4xx/5xx."""
        delay = self._retry_backoff_s
        for attempt in range(self._max_retries + 1):
            try:
                return await self._post_once(payload)
            except LLMResponseError as exc:
                if not exc.retryable or attempt == self._max_retries:
                    raise
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                retryable = status == 429 or 500 <= status < 600
                if not retryable or attempt == self._max_retries:
                    raise
            except httpx.TransportError:
                if attempt == self._max_retries:
                    raise
            # Transient: back off with up to 25% jitter before the next attempt.
            await asyncio.sleep(delay + random.uniform(0.0, delay * 0.25))
            delay = min(delay * 2.0, 2.0)
        raise LLMResponseError("retries exhausted", retryable=False)

    async def _post_once(self, payload: dict) -> tuple[int, dict]:
        t0 = time.perf_counter()
        resp = await self._client.post(f"{self._base_url}/chat/completions", json=payload)
        resp.raise_for_status()  # HTTPStatusError on 4xx/5xx (classified in _post)
        try:
            data = resp.json()
        except _json.JSONDecodeError as exc:
            raise LLMResponseError(f"non-JSON response body: {exc}", retryable=True) from exc
        self._validate_choices(data)
        latency_ms = round((time.perf_counter() - t0) * 1000)
        return latency_ms, data

    @staticmethod
    def _validate_choices(data: object) -> None:
        """Guard the response shape so a truncated/empty 200 raises a clean
        retryable error instead of a KeyError/IndexError escaping the caller."""
        if not isinstance(data, dict):
            raise LLMResponseError("response body is not a JSON object", retryable=True)
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            raise LLMResponseError("response has no choices", retryable=True)
        first = choices[0]
        if not isinstance(first, dict) or "message" not in first:
            raise LLMResponseError("response choice has no message", retryable=True)
