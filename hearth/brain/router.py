"""Router seam: selects a Brain for a turn. Local-only in this feather.

FTHR-004 replaces the body with real tier logic without changing `Selection`
or `select`'s signature.
"""
from __future__ import annotations

from dataclasses import dataclass

import httpx

from hearth.brain.base import Brain
from hearth.brain.local import LocalBackend
from hearth.config import LLMConfig


@dataclass
class Selection:
    brain: Brain
    tier: str
    backend_name: str
    reason: str


class Router:
    def __init__(self, config: LLMConfig, client: httpx.AsyncClient) -> None:
        self._config = config
        self._client = client

    def select(
        self, tools_available: bool = False, tier_override: str | None = None
    ) -> Selection:
        tier = tier_override or "default"
        backend_name = self._config.tiers.default
        backend_config = self._config.backends[backend_name]
        brain = LocalBackend(
            backend_config, client=self._client, name=backend_name, tier=tier
        )
        return Selection(
            brain=brain,
            tier=tier,
            backend_name=backend_name,
            reason="single-backend (FTHR-002)",
        )
