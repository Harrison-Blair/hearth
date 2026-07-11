"""LocalBackend: OpenAI-compatible chat-completion backend (non-streaming)."""
from __future__ import annotations

import httpx

from hearth.brain.openai_compat import _OpenAICompatBackend
from hearth.config import LLMBackend


class LocalBackend(_OpenAICompatBackend):
    """A `Brain` backed by an OpenAI-compatible `/chat/completions` endpoint."""

    def __init__(
        self,
        config: LLMBackend,
        client: httpx.AsyncClient,
        name: str = "local",
        tier: str = "default",
        max_retries: int = 0,
    ) -> None:
        super().__init__(config, client, name=name, tier=tier, max_retries=max_retries)
