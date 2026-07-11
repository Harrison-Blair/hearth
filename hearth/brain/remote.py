"""RemoteBackend: OpenRouter, OpenAI-compatible chat-completion backend."""
from __future__ import annotations

import httpx

from hearth.brain.openai_compat import _OpenAICompatBackend
from hearth.config import LLMBackend


class RemoteBackend(_OpenAICompatBackend):
    """A `Brain` backed by OpenRouter's OpenAI-compatible `/chat/completions` endpoint."""

    def __init__(
        self,
        config: LLMBackend,
        client: httpx.AsyncClient,
        name: str = "remote",
        tier: str = "tool",
    ) -> None:
        super().__init__(config, client, name=name, tier=tier)
