"""sounddevice-backed audio output (PortAudio)."""

from __future__ import annotations

import asyncio
import logging

import numpy as np
import sounddevice as sd

from assistant.audio.base import AudioOut

log = logging.getLogger(__name__)


class SoundDeviceOut(AudioOut):
    """Plays mono int16 PCM through a fixed device at a fixed sample rate.

    Constructed with the producer's sample rate (e.g. the TTS voice rate), so
    the ``play(bytes)`` contract stays rate-free.
    """

    def __init__(self, device: int, sample_rate: int, channels: int = 1) -> None:
        self._device = device
        self._sample_rate = sample_rate
        self._channels = channels

    async def play(self, audio: bytes) -> None:
        await asyncio.to_thread(self._play, audio)

    def _play(self, audio: bytes) -> None:
        samples = np.frombuffer(audio, dtype=np.int16)
        sd.play(samples, samplerate=self._sample_rate, device=self._device)
        sd.wait()
