"""Text-to-speech interface."""

from __future__ import annotations

from abc import ABC, abstractmethod


class TextToSpeech(ABC):
    @abstractmethod
    async def synthesize(self, text: str, length_scale: float | None = None) -> bytes:
        """Synthesize text to PCM audio.

        ``length_scale`` optionally overrides the speaking rate for this call
        (>1 slower, <1 faster); None uses the backend's configured default.
        """
