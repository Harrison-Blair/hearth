"""LLM provider interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from assistant.core.events import ToolCall


@dataclass
class ChatResponse:
    """A tool-calling chat reply: either spoken ``content``, one or more
    ``tool_calls``, or both. Empty on both means the model produced nothing usable."""

    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)


class LLMProvider(ABC):
    @abstractmethod
    async def complete(
        self, prompt: str, *, system: str | None = None, json: bool = False, label: str = ""
    ) -> str:
        """Return a completion for the prompt. If json=True, the model is asked
        to return a single JSON object. ``label`` tags the call's purpose for the
        diagnostic log trace (e.g. "classify", "answer")."""

    @abstractmethod
    async def chat(
        self, messages: list[dict], *, system: str | None = None, label: str = ""
    ) -> str:
        """Return the assistant reply for a role/content message list. ``system``,
        when given, is prepended as a system message. ``label`` tags the call's
        purpose for the diagnostic log trace."""

    @abstractmethod
    async def chat_tools(
        self,
        messages: list[dict],
        *,
        system: str | None = None,
        tools: list[dict] | None = None,
        label: str = "",
    ) -> ChatResponse:
        """Return a tool-calling reply for a message list. ``tools`` is a list of
        OpenAI-style function schemas the model may call; the reply carries either
        spoken content, tool calls, or both. ``system`` is prepended as a system
        message. ``label`` tags the call's purpose for the diagnostic log trace."""

    @abstractmethod
    async def health(self) -> bool:
        """Return True if the provider is reachable and ready."""

    async def aclose(self) -> None:
        """Release any held resources (e.g. an HTTP client). No-op by default."""
