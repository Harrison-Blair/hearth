"""LLM completions via a local Ollama server (offline once the model is pulled)."""

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


class OllamaProvider(LLMProvider):
    def __init__(
        self,
        model: str,
        host: str = "http://localhost:11434",
        timeout: float = 60.0,
        health_timeout: float = 5.0,
        num_ctx: int = 8192,
        think: bool = False,
    ) -> None:
        self._model = model
        self._host = host.rstrip("/")
        self._timeout = timeout
        self._health_timeout = health_timeout
        self._num_ctx = num_ctx
        self._think = think
        # One pooled client reused across every call (a voice turn makes 2+):
        # constructing a fresh client per request loses keep-alive entirely.
        self._client = httpx.AsyncClient(timeout=timeout)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def complete(
        self, prompt: str, *, system: str | None = None, json: bool = False, label: str = ""
    ) -> str:
        payload: dict = {
            "model": self._model,
            "prompt": prompt,
            "stream": False,
            "options": {"num_ctx": self._num_ctx},
        }
        if system:
            payload["system"] = system
        # Thinking models emit their reasoning into the grammar-constrained JSON
        # output (corrupting it) and prepend a spoken <think> block on the plain
        # path, so force think off for JSON and honor self._think otherwise.
        payload["think"] = False if json else self._think
        if json:
            payload["format"] = "json"

        t0 = time.perf_counter()
        resp = await self._client.post(f"{self._host}/api/generate", json=payload)
        resp.raise_for_status()
        latency_ms = round((time.perf_counter() - t0) * 1000)
        data = resp.json()
        response = data.get("response", "").strip()
        tag = label or "llm"
        log.info("[%s] prompt: %s", tag, _clip(prompt, 200))
        if system:
            log.info("[%s] system: %s", tag, _clip(system, 120))
        # Console stays clipped; the full trace rides `data` into the JSONL file.
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
        payload = {
            "model": self._model,
            "messages": msgs,
            "stream": False,
            "think": self._think,
            "options": {"num_ctx": self._num_ctx},
        }

        t0 = time.perf_counter()
        resp = await self._client.post(f"{self._host}/api/chat", json=payload)
        resp.raise_for_status()
        latency_ms = round((time.perf_counter() - t0) * 1000)
        data = resp.json()
        response = data["message"]["content"].strip()
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
        payload: dict = {
            "model": self._model,
            "messages": msgs,
            "stream": False,
            "think": self._think,
            "options": {"num_ctx": self._num_ctx},
        }
        if tools:
            payload["tools"] = tools

        t0 = time.perf_counter()
        resp = await self._client.post(f"{self._host}/api/chat", json=payload)
        resp.raise_for_status()
        latency_ms = round((time.perf_counter() - t0) * 1000)
        message = resp.json().get("message", {})
        content = (message.get("content") or "").strip()
        calls: list[ToolCall] = []
        for tc in message.get("tool_calls") or []:
            fn = tc.get("function", {})
            name = fn.get("name")
            if not name:
                continue
            args = fn.get("arguments")
            if isinstance(args, str):
                # Some models return the arguments as a JSON string, not an object.
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
                f"{self._host}/api/tags", timeout=self._health_timeout
            )
            resp.raise_for_status()
            models = [m["name"] for m in resp.json().get("models", [])]
        except (httpx.HTTPError, _json.JSONDecodeError, KeyError) as exc:
            log.warning("Ollama health check failed: %s", exc)
            return False
        # Match on the base name so "qwen2.5:3b-instruct" matches "...:latest" tags too.
        base = self._model.split(":")[0]
        if not any(m.split(":")[0] == base for m in models):
            log.warning("Ollama is up but model %r is not pulled (have: %s)", self._model, models)
            return False
        return True
