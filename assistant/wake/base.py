"""Wake-word detector interface."""

from __future__ import annotations

from abc import ABC, abstractmethod

from assistant.core.events import WakeEvent


class WakeDetector(ABC):
    @abstractmethod
    def process(self, frame: bytes) -> WakeEvent | None:
        """Feed one audio frame; return a WakeEvent if the wake word fired."""

    @abstractmethod
    def reset(self) -> None:
        """Clear internal state after a detection (avoids immediate re-trigger)."""
