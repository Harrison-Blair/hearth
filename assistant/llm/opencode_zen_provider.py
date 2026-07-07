"""LLM completions via OpenCode Zen (OpenAI-compatible /chat/completions).

Same ``LLMProvider`` contract as ``OllamaProvider``; differs only in wire shape.
Models live server-side, so ``health`` just checks the gateway answers, not that
a specific model is pulled.
"""

from __future__ import annotations

import json as _json
import logging
import time

import httpx

from assistant.core.events import ToolCall
from assistant.llm.base import ChatResponse, LLMProvider

log = logging.getLogger(__name__)


def _clip(s: str, n: int) -> str:
    return s if len(s) <= n else s[:n] + "…"


class OpenCodeZenProvider(LLMProvider):
    def __init__(
        self,
        model: str,
        api_key: str,
        base_url: str = "https://opencode.ai/zen/v1",
        timeout: float = 60.0,
        health_timeout: float = 5.0,
    ) -> None:
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._health_timeout = health_timeout
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
        t0 = time.perf_counter()
        resp = await self._client.post(f"{self._base_url}/chat/completions", json=payload)
        resp.raise_for_status()
        latency_ms = round((time.perf_counter() - t0) * 1000)
        return latency_ms, resp.json()
