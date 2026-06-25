"""Speech-to-text interface."""

from __future__ import annotations

from abc import ABC, abstractmethod


class SpeechToText(ABC):
    @abstractmethod
    async def transcribe(self, audio: bytes) -> str:
        """Transcribe PCM audio to text."""
