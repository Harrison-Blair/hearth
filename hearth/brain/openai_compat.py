"""Shared OpenAI-compatible chat-completion request/parse logic.

Extracted from FTHR-002's `LocalBackend` so `LocalBackend` and `RemoteBackend`
(FTHR-004) can both be thin config-bound subclasses.
"""
from __future__ import annotations

import json

import httpx

from hearth.brain.base import BrainResult, Capabilities, Message, ToolCall, ToolSpec
from hearth.brain.errors import BrainError
from hearth.config import LLMBackend


def _message_to_dict(message: Message) -> dict:
    payload: dict = {"role": message.role, "content": message.content}
    if message.tool_calls:
        payload["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)},
            }
            for tc in message.tool_calls
        ]
    if message.tool_call_id:
        payload["tool_call_id"] = message.tool_call_id
    return payload


def _tool_to_dict(tool: ToolSpec) -> dict:
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.parameters,
        },
    }


class _OpenAICompatBackend:
    """A `Brain` backed by an OpenAI-compatible `/chat/completions` endpoint."""

    def __init__(
        self,
        config: LLMBackend,
        client: httpx.AsyncClient,
        name: str,
        tier: str,
        max_retries: int = 0,
    ) -> None:
        self._config = config
        self._client = client
        self._max_retries = max_retries
        self.name = name
        self.tier = tier
        self.capabilities = Capabilities(
            supports_tools=config.supports_tools,
            supports_streaming=config.supports_streaming,
            context_window=config.context_window,
            cost_tier=config.cost_tier,
        )

    async def complete(
        self, messages: list[Message], tools: list[ToolSpec] | None = None
    ) -> BrainResult:
        payload: dict = {
            "model": self._config.model,
            "messages": [_message_to_dict(m) for m in messages],
            "stream": False,
        }
        if tools:
            payload["tools"] = [_tool_to_dict(t) for t in tools]

        headers = {}
        api_key = self._config.resolve_api_key()
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        # Retry only transient connection/network blips (up to max_retries).
        # A timeout means the model is already too slow -- retrying just
        # re-hits it and burns the turn budget -- and an HTTP status error
        # won't change on retry, so neither is retried. A status error was
        # served by a reachable backend, so it gets its own reason ("backend
        # error", e.g. a bad key or rate limit) instead of "backend
        # unreachable".
        attempt = 0
        while True:
            try:
                response = await self._client.post(
                    "/chat/completions", json=payload, headers=headers
                )
                response.raise_for_status()
                break
            except httpx.TimeoutException as exc:
                raise BrainError("backend unreachable", detail=str(exc)) from exc
            except httpx.TransportError as exc:
                if attempt >= self._max_retries:
                    raise BrainError("backend unreachable", detail=str(exc)) from exc
                attempt += 1
            except httpx.HTTPStatusError as exc:
                detail = f"HTTP {exc.response.status_code}: {exc.response.text[:200]}"
                raise BrainError("backend error", detail=detail) from exc
            except httpx.HTTPError as exc:
                raise BrainError("backend unreachable", detail=str(exc)) from exc

        body = response.json()
        try:
            choice = body["choices"][0]
            message = choice["message"]
        except (KeyError, IndexError) as exc:
            raise BrainError(
                "unreadable response", detail=f"malformed body: {body!r}"[:500]
            ) from exc

        try:
            tool_calls = [
                ToolCall(
                    id=tc["id"],
                    name=tc["function"]["name"],
                    arguments=json.loads(tc["function"]["arguments"]),
                )
                for tc in message.get("tool_calls") or []
            ]
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            # Bad arguments JSON, or a tool call missing id/function/name.
            raise BrainError(
                "unreadable response", detail=f"bad tool call: {exc!r}"
            ) from exc

        return BrainResult(
            text=message.get("content"),
            tool_calls=tool_calls,
            finish_reason=choice.get("finish_reason", "stop"),
            backend=self.name,
            tier=self.tier,
        )
