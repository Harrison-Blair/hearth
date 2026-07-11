"""Router seam: selects a Brain for a turn via deterministic, config-driven tier routing."""
from __future__ import annotations

from dataclasses import dataclass

import httpx

from hearth.brain.base import Brain
from hearth.brain.local import LocalBackend
from hearth.brain.remote import RemoteBackend
from hearth.config import LLMConfig

# Tier role -> backend class. `tiers.default` always resolves to the local
# backend, `tiers.tool` always resolves to the remote (OpenRouter) backend.
_BACKEND_CLASS_FOR_TIER = {"default": LocalBackend, "tool": RemoteBackend}


@dataclass
class Selection:
    brain: Brain
    tier: str
    backend_name: str
    reason: str


class Router:
    def __init__(self, config: LLMConfig, clients: dict[str, httpx.AsyncClient]) -> None:
        self._config = config
        self._clients = clients

    def _build(self, tier: str) -> Selection:
        backend_name = getattr(self._config.tiers, tier)
        backend_config = self._config.backends[backend_name]
        brain_cls = _BACKEND_CLASS_FOR_TIER[tier]
        client = self._clients[backend_name]
        brain = brain_cls(backend_config, client=client, name=backend_name, tier=tier)
        return Selection(brain=brain, tier=tier, backend_name=backend_name, reason="")

    def select(self, tier_override: str | None = None) -> Selection:
        if tier_override:
            selection = self._build(tier_override)
            selection.reason = f"override:{tier_override}"
            return selection

        selection = self._build("default")
        selection.reason = "chat-turn→default tier"
        return selection

    def brain_available(self) -> bool:
        """Whether the `tool` tier backend can serve a `consult_brain` call
        right now -- lets `Loop` decide once per turn whether to offer the
        tool at all, preserving PLM-001's local-only fallback."""
        tool_backend_name = self._config.tiers.tool
        tool_config = self._config.backends[tool_backend_name]
        return tool_config.enabled and tool_config.supports_tools
