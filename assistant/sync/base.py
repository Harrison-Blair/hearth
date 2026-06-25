"""Sync adapter interface — no-op in the MVP.

Leaves room for real Google Calendar sync later without touching skill code.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class SyncAdapter(ABC):
    @abstractmethod
    async def push(self, event: Any) -> None:
        """Push a local change upstream."""

    @abstractmethod
    async def pull(self) -> list[Any]:
        """Pull upstream changes."""


class NoopSyncAdapter(SyncAdapter):
    """MVP stub: persistence is local-only, so sync does nothing."""

    async def push(self, event: Any) -> None:
        return None

    async def pull(self) -> list[Any]:
        return []
