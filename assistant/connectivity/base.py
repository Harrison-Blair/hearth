"""Connectivity check + provider routing interfaces.

The concrete health-checked router lands in Phase 6. Local is always the
guaranteed fallback for every capability.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class ConnectivityService(ABC):
    @abstractmethod
    async def is_online(self) -> bool:
        """Return True if the device currently has internet access."""


class ProviderRouter(ABC):
    @abstractmethod
    def get(self, capability: str) -> Any:
        """Return the active implementation for a capability (Local or Remote)."""
