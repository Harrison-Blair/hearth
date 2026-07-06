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
        self._queue: asyncio.Queue[bytes] | None = None

    def drain(self) -> None:
        """Discard frames buffered while an earcon/TTS played, so their echo isn't
        recorded as part of the next command."""
        queue = self._queue
        if queue is None:
            return
        dropped = 0
        while not queue.empty():
            try:
                queue.get_nowait()
                dropped += 1
            except asyncio.QueueEmpty:
                break
        if dropped:
            log.debug("drained %d buffered input frame(s)", dropped)

    async def stream(self) -> AsyncIterator[bytes]:
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[bytes] = asyncio.Queue()
        self._queue = queue

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

    def set_volume(self, volume: float) -> None:
        """Adjust playback gain live (used by the control channel for mute/volume)."""
        self._volume = max(0.0, volume)
        log.info("Output volume set to %.2f", self._volume)

    def stop(self) -> None:
        """Abort in-progress playback for barge-in; the blocked ``sd.wait()`` in
        ``_play`` then returns and the current utterance is cut short."""
        try:
            sd.stop()
        except Exception as exc:  # noqa: BLE001 - stop must never raise into the caller
            log.debug("audio stop failed: %s", exc)

    async def play(self, audio: bytes) -> None:
        await asyncio.to_thread(self._play, audio)

    def _play(self, audio: bytes) -> None:
        samples = np.frombuffer(audio, dtype=np.int16)
        if self._volume != 1.0:
            scaled = samples.astype(np.float32) * self._volume
            samples = np.clip(scaled, -32768, 32767).astype(np.int16)
        sd.play(samples, samplerate=self._sample_rate, device=self._device)
        sd.wait()
