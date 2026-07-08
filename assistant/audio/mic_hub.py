"""Mic fan-out hub: one pump task, one primary stream, one optional tap.

``VoicePipeline.run`` consumes the mic through a single async generator, so
while a turn is inside playback nothing pulls frames and the wake detector goes
deaf. The hub decouples that: its pump task reads the inner device continuously,
buffers frames for the primary ``stream()`` consumer, and hands every frame to a
synchronous tap callback when one is set — that's what lets the pipeline score
the wake word *while it is speaking* (barge-in).

An optional ``processor`` (e.g. the echo canceller) transforms each frame before
both the buffer and the tap, so the recorder and the barge watcher see the same
cleaned audio.
"""

from __future__ import annotations

import asyncio
import logging
from typing import AsyncIterator, Callable

from assistant.audio.base import AudioIn

log = logging.getLogger(__name__)


class MicHub(AudioIn):
    def __init__(
        self,
        inner: AudioIn,
        processor: Callable[[bytes], bytes] | None = None,
        maxsize: int = 64,
    ) -> None:
        self._inner = inner
        self._processor = processor
        # Bounded so a consumer stalled in playback can't buffer unbounded audio;
        # on overflow the oldest frame is dropped to keep the stream realtime.
        self._queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize)
        self._tap: Callable[[bytes], None] | None = None
        self._pump_task: asyncio.Task | None = None

    def set_tap(self, tap: Callable[[bytes], None]) -> None:
        self._tap = tap

    def clear_tap(self) -> None:
        self._tap = None

    def drain(self) -> None:
        while not self._queue.empty():
            self._queue.get_nowait()
        self._inner.drain()

    def stream(self) -> AsyncIterator[bytes]:
        # Sync (unlike the device implementations' async generators, which the
        # ABC also allows): the pump must be live from the moment the caller
        # grabs the stream, not from its first __anext__, so the tap works even
        # before/without a consumer.
        if self._pump_task is None:
            self._pump_task = asyncio.create_task(self._pump())
        return self._frames()

    async def _frames(self) -> AsyncIterator[bytes]:
        while True:
            yield await self._queue.get()

    async def _pump(self) -> None:
        async for frame in self._inner.stream():
            if self._processor is not None:
                frame = self._processor(frame)
            tap = self._tap
            if tap is not None:
                try:
                    tap(frame)
                except Exception:  # noqa: BLE001 - a tap bug must not kill the mic
                    log.exception("mic tap failed")
            if self._queue.full():
                self._queue.get_nowait()  # drop oldest, keep realtime
            self._queue.put_nowait(frame)
