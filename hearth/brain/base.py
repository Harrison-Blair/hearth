"""Boundary types for the Brain protocol.

These signatures are frozen: FTHR-004 (router) and FTHR-006 (tools) build on
them without changing shape. `BrainResult` is the one exception: its shape is
frozen for router/tool call sites, but it may gain additive, defaulted
observability fields (FTHR-013's metrics capture) without breaking them.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass
class Capabilities:
    supports_tools: bool
    supports_streaming: bool
    context_window: int
    cost_tier: str


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class Message:
    role: str
    content: str | None
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict
    label: str


@dataclass
class BrainResult:
    text: str | None
    tool_calls: list[ToolCall] = field(default_factory=list)
    finish_reason: str = "stop"
    backend: str = ""
    tier: str = ""
    model: str = ""
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    reasoning_tokens: int | None = None
    total_tokens: int | None = None
    duration_s: float | None = None


@runtime_checkable
class Brain(Protocol):
    capabilities: Capabilities

    async def complete(
        self, messages: list[Message], tools: list[ToolSpec] | None
    ) -> BrainResult: ...
