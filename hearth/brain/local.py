"""LocalBackend: OpenAI-compatible chat-completion backend (non-streaming)."""
from __future__ import annotations

import json

import httpx

from hearth.brain.base import BrainResult, Capabilities, Message, ToolCall, ToolSpec
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


class LocalBackend:
    """A `Brain` backed by an OpenAI-compatible `/chat/completions` endpoint."""

    def __init__(
        self,
        config: LLMBackend,
        client: httpx.AsyncClient,
        name: str = "local",
        tier: str = "default",
    ) -> None:
        self._config = config
        self._client = client
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

        response = await self._client.post(
            "/chat/completions", json=payload, headers=headers
        )
        response.raise_for_status()
        body = response.json()
        choice = body["choices"][0]
        message = choice["message"]

        tool_calls = [
            ToolCall(
                id=tc["id"],
                name=tc["function"]["name"],
                arguments=json.loads(tc["function"]["arguments"]),
            )
            for tc in message.get("tool_calls") or []
        ]

        return BrainResult(
            text=message.get("content"),
            tool_calls=tool_calls,
            finish_reason=choice.get("finish_reason", "stop"),
            backend=self.name,
            tier=self.tier,
        )
