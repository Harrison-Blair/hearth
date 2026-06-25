"""AudioArbiter — a single async lock guarding the audio device.

Playback (TTS, proactive announcements) and capture (recording an utterance)
must never run at once: a proactive reminder should wait for capture to finish,
and capture should pause wake detection. Both acquire the same lock.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

log = logging.getLogger(__name__)


class AudioArbiter:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()

    @property
    def busy(self) -> bool:
        return self._lock.locked()

    @asynccontextmanager
    async def hold(self, who: str) -> AsyncIterator[None]:
        if self._lock.locked():
            log.debug("audio busy, %s waiting", who)
        async with self._lock:
            log.debug("audio held by %s", who)
            yield
