"""LLM provider interface."""

from __future__ import annotations

from abc import ABC, abstractmethod


class LLMProvider(ABC):
    @abstractmethod
    async def complete(
        self, prompt: str, *, system: str | None = None, json: bool = False, label: str = ""
    ) -> str:
        """Return a completion for the prompt. If json=True, the model is asked
        to return a single JSON object. ``label`` tags the call's purpose for the
        diagnostic log trace (e.g. "classify", "answer")."""

    @abstractmethod
    async def health(self) -> bool:
        """Return True if the provider is reachable and ready."""

    async def aclose(self) -> None:
        """Release any held resources (e.g. an HTTP client). No-op by default."""
