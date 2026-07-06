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

# Spoken once on boot when the app was off as several reminders came due, so the
# user hears one "while I was away" recap instead of a burst of separate alerts.
_AWAY_PREAMBLE = "While I was away, {n} reminders came due."


class ReminderScheduler:
    def __init__(
        self,
        store: ReminderStore,
        tts: TextToSpeech,
        audio_out: AudioOut,
        arbiter: AudioArbiter,
        *,
        poll_seconds: float = 1.0,
        max_attempts: int = 3,
        now: Callable[[], float] = time.time,
    ) -> None:
        self._store = store
        self._tts = tts
        self._audio_out = audio_out
        self._arbiter = arbiter
        self._poll_seconds = poll_seconds
        self._max_attempts = max_attempts
        self._now = now
        # Per-reminder failure counter: a transient audio error retries on the next
        # poll instead of losing the reminder, but only up to _max_attempts so an
        # un-speakable one can't loop forever.
        self._attempts: dict[int, int] = {}
        # The first poll returns the whole backlog that came due while we were off;
        # coalesce it into one announcement. Steady-state polls fire one at a time.
        self._first_poll = True

    async def run(self) -> None:
        log.info("Reminder scheduler started (poll=%.1fs)", self._poll_seconds)
        while True:
            due = self._store.due(self._now())
            if self._first_poll and len(due) > 1:
                await self._fire_summary(due)
            else:
                for reminder in due:
                    await self._fire(reminder)
            self._first_poll = False
            await asyncio.sleep(self._poll_seconds)

    async def _fire(self, reminder) -> None:
        try:
            log.info("Reminder due: %r", reminder.speech)
            async with self._arbiter.hold("reminder"):
                await self._audio_out.play(await self._tts.synthesize(reminder.speech))
        except Exception as exc:  # noqa: BLE001 - one failure must not kill the loop
            log.error("Failed to fire reminder %s: %s", reminder.id, exc)
            self._attempts[reminder.id] = self._attempts.get(reminder.id, 0) + 1
            # Retry on the next poll until we've exhausted the budget; only then drop
            # the row, so a permanently un-speakable reminder can't loop forever.
            if self._attempts[reminder.id] >= self._max_attempts:
                self._store.delete(reminder.id)
                del self._attempts[reminder.id]
        else:
            self._store.delete(reminder.id)
            self._attempts.pop(reminder.id, None)

    async def _fire_summary(self, due) -> None:
        try:
            log.info("Catch-up: %d reminders came due while away", len(due))
            text = _AWAY_PREAMBLE.format(n=len(due)) + " " + " ".join(r.speech for r in due)
            async with self._arbiter.hold("reminder"):
                await self._audio_out.play(await self._tts.synthesize(text))
        except Exception as exc:  # noqa: BLE001 - one failure must not kill the loop
            # Don't delete: _first_poll flips to False, so the backlog is re-fired
            # individually via _fire (which carries per-id retry) on the next poll.
            log.error("Failed to announce catch-up summary: %s", exc)
        else:
            for reminder in due:
                self._store.delete(reminder.id)
