"""LLM completions via a local Ollama server (offline once the model is pulled)."""

from __future__ import annotations

import json as _json
import logging

import httpx

from assistant.llm.base import LLMProvider

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
    ) -> None:
        self._model = model
        self._host = host.rstrip("/")
        self._timeout = timeout
        self._health_timeout = health_timeout
        # One pooled client reused across every call (a voice turn makes 2+):
        # constructing a fresh client per request loses keep-alive entirely.
        self._client = httpx.AsyncClient(timeout=timeout)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def complete(
        self, prompt: str, *, system: str | None = None, json: bool = False, label: str = ""
    ) -> str:
        payload: dict = {"model": self._model, "prompt": prompt, "stream": False}
        if system:
            payload["system"] = system
        if json:
            payload["format"] = "json"

        resp = await self._client.post(f"{self._host}/api/generate", json=payload)
        resp.raise_for_status()
        data = resp.json()
        response = data.get("response", "").strip()
        tag = label or "llm"
        log.info("[%s] prompt: %s", tag, _clip(prompt, 200))
        if system:
            log.info("[%s] system: %s", tag, _clip(system, 120))
        log.info("[%s] response: %s", tag, response)
        return response

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
