"""Audio I/O interfaces."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import AsyncIterator


class AudioOut(ABC):
    @abstractmethod
    async def play(self, audio: bytes) -> None:
        """Play PCM audio through the configured output device."""

    def stop(self) -> None:
        """Abort any in-progress playback (barge-in). Safe to call when idle.

        Default no-op; blocking-playback implementations override it. Called from a
        different task than ``play()`` (the control channel), so it must be sync."""


class AudioIn(ABC):
    @abstractmethod
    def stream(self) -> AsyncIterator[bytes]:
        """Yield fixed-size PCM frames from the configured input device."""

    def drain(self) -> None:
        """Discard any buffered-but-unconsumed input frames.

        Called after the assistant plays a cue through the speaker, so that cue's
        echo (captured while it played) isn't fed to STT as part of the command.
        Default no-op; stream-buffered implementations override it.
        """
