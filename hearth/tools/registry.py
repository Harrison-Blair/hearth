"""ToolRegistry seam. Empty in this feather; FTHR-006 populates it."""
from __future__ import annotations

from hearth.brain.base import ToolSpec


class ToolRegistry:
    def specs(self) -> list[ToolSpec]:
        return []

    async def dispatch(self, name: str, args: dict) -> str:
        raise KeyError(f"no tool registered: {name}")
