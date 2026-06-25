"""sounddevice-backed audio I/O (PortAudio)."""

from __future__ import annotations

import asyncio
import logging
from typing import AsyncIterator

import numpy as np
import sounddevice as sd

from assistant.audio.base import AudioIn, AudioOut

log = logging.getLogger(__name__)


class SoundDeviceIn(AudioIn):
    """Streams fixed-size mono int16 PCM frames from the input device.

    A PortAudio callback (its own thread) pushes frames into an asyncio queue;
    ``stream()`` yields them on the event loop.
    """

    def __init__(
        self,
        device: int,
        sample_rate: int = 16000,
        block_size: int = 1280,
        channels: int = 1,
    ) -> None:
        self._device = device
        self._sample_rate = sample_rate
        self._block_size = block_size
        self._channels = channels

    async def stream(self) -> AsyncIterator[bytes]:
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[bytes] = asyncio.Queue()

        def callback(indata, frames, time_info, status):  # PortAudio thread
            if status:
                log.warning("input stream status: %s", status)
            loop.call_soon_threadsafe(queue.put_nowait, bytes(indata))

        with sd.InputStream(
            samplerate=self._sample_rate,
            blocksize=self._block_size,
            device=self._device,
            channels=self._channels,
            dtype="int16",
            callback=callback,
        ):
            while True:
                yield await queue.get()


class SoundDeviceOut(AudioOut):
    """Plays mono int16 PCM through a fixed device at a fixed sample rate.

    Constructed with the producer's sample rate (e.g. the TTS voice rate), so
    the ``play(bytes)`` contract stays rate-free.
    """

    def __init__(
        self, device: int, sample_rate: int, channels: int = 1, volume: float = 1.0
    ) -> None:
        self._device = device
        self._sample_rate = sample_rate
        self._channels = channels
        self._volume = volume

    async def play(self, audio: bytes) -> None:
        await asyncio.to_thread(self._play, audio)

    def _play(self, audio: bytes) -> None:
        samples = np.frombuffer(audio, dtype=np.int16)
        if self._volume != 1.0:
            scaled = samples.astype(np.float32) * self._volume
            samples = np.clip(scaled, -32768, 32767).astype(np.int16)
        sd.play(samples, samplerate=self._sample_rate, device=self._device)
        sd.wait()
