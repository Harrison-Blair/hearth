"""ToolRegistry: populates the FTHR-002 seam with the wikipedia_search tool.

Shape stays the same as the empty seam (`specs()` / `dispatch()`) so future
tools register the same way. With no config/client wired in, `specs()` stays
empty — the seam's original no-op behavior.
"""
from __future__ import annotations

from typing import Optional

import httpx

from hearth.brain.base import ToolSpec
from hearth.config import ToolConfig
from hearth.tools import wikipedia


class ToolRegistry:
    def __init__(
        self,
        tool_config: Optional[ToolConfig] = None,
        client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        self._config = tool_config
        self._client = client

    def specs(self) -> list[ToolSpec]:
        if self._config is None or self._client is None or not self._config.wikipedia_enabled:
            return []
        return [wikipedia.SPEC]

    async def dispatch(self, name: str, args: dict) -> str:
        if name == "wikipedia_search" and self.specs():
            return await wikipedia.wikipedia_search(
                args["query"],
                client=self._client,
                endpoint=self._config.wikipedia_endpoint,
                result_count=self._config.wikipedia_result_count,
                max_chars=self._config.wikipedia_max_chars,
                lang=self._config.wikipedia_language,
                timeout=self._config.wikipedia_timeout,
            )
        raise KeyError(f"no tool registered: {name}")
