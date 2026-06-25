"""Wake-word detector interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import AsyncIterator

from assistant.core.events import WakeEvent


class WakeDetector(ABC):
    @abstractmethod
    def stream(self, frames: AsyncIterator[bytes]) -> AsyncIterator[WakeEvent]:
        """Consume audio frames and yield a WakeEvent on each activation."""
