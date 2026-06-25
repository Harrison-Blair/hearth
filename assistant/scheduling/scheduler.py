"""Fires due reminders by speaking them, even while the assistant is idle.

A plain asyncio poll loop over the ReminderStore (the source of truth). Each
announcement is serialized against the voice pipeline through the shared
AudioArbiter, so it never plays over a capture and never self-triggers the wake
word. Reminders that came due while the process was down are returned by the
first poll and spoken on boot (catch-up).
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Callable

from assistant.audio.base import AudioOut
from assistant.core.arbiter import AudioArbiter
from assistant.storage.reminders import ReminderStore
from assistant.tts.base import TextToSpeech

log = logging.getLogger(__name__)


class ReminderScheduler:
    def __init__(
        self,
        store: ReminderStore,
        tts: TextToSpeech,
        audio_out: AudioOut,
        arbiter: AudioArbiter,
        *,
        poll_seconds: float = 1.0,
        now: Callable[[], float] = time.time,
    ) -> None:
        self._store = store
        self._tts = tts
        self._audio_out = audio_out
        self._arbiter = arbiter
        self._poll_seconds = poll_seconds
        self._now = now

    async def run(self) -> None:
        log.info("Reminder scheduler started (poll=%.1fs)", self._poll_seconds)
        while True:
            for reminder in self._store.due(self._now()):
                await self._fire(reminder)
            await asyncio.sleep(self._poll_seconds)

    async def _fire(self, reminder) -> None:
        try:
            log.info("Reminder due: %r", reminder.speech)
            async with self._arbiter.hold("reminder"):
                await self._audio_out.play(await self._tts.synthesize(reminder.speech))
            self._store.mark_fired(reminder.id)
        except Exception as exc:  # noqa: BLE001 - one failure must not kill the loop
            log.error("Failed to fire reminder %s: %s", reminder.id, exc)
