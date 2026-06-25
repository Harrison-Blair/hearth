"""Audio I/O interfaces."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import AsyncIterator


class AudioOut(ABC):
    @abstractmethod
    async def play(self, audio: bytes) -> None:
        """Play PCM audio through the configured output device."""


class AudioIn(ABC):
    @abstractmethod
    def stream(self) -> AsyncIterator[bytes]:
        """Yield fixed-size PCM frames from the configured input device."""
