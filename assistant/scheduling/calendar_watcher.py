"""Announces upcoming calendar events, even while the assistant is idle.

Same shape as ReminderScheduler: a plain asyncio poll loop, each announcement
serialized against the voice pipeline through the shared AudioArbiter. Every
poll fetches events starting within the lead window from each watched calendar
and speaks the ones not yet announced. Dedupe is persisted per (event id,
start epoch) — a restart inside the lead window stays silent, a rescheduled
event gets a fresh key and is announced again with its new time, and a
cancelled event simply stops appearing. The `enabled` flag is flipped at
runtime by the calendar skill's voice toggle; the loop keeps ticking while
disabled so a later "start watching" needs no new task.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Callable

from assistant.audio.base import AudioOut
from assistant.calendar.base import CalendarProvider, speakable_title
from assistant.calendar.blocklist import EventBlocklist
from assistant.core.arbiter import AudioArbiter
from assistant.core.revoice import Revoicer
from assistant.core.standdown import StandDown
from assistant.skills.base import local_now
from assistant.storage.calendar_state import CalendarStateStore
from assistant.tts.base import TextToSpeech

log = logging.getLogger(__name__)

_PURGE_AFTER_S = 86400.0  # drop dedupe rows a day after the event started


class CalendarWatcher:
    def __init__(
        self,
        provider: CalendarProvider,
        state: CalendarStateStore,
        tts: TextToSpeech,
        audio_out: AudioOut,
        arbiter: AudioArbiter,
        *,
        blocklist: EventBlocklist,
        calendar_ids: list[str],
        poll_seconds: float = 300.0,
        lead_minutes: int = 15,
        enabled: bool = True,
        now: Callable[[], datetime] = local_now,
        standdown: StandDown | None = None,
        revoicer: Revoicer | None = None,
    ) -> None:
        self._provider = provider
        self._state = state
        self._tts = tts
        self._audio_out = audio_out
        self._arbiter = arbiter
        self._blocklist = blocklist
        self._calendar_ids = calendar_ids
        self._poll_seconds = poll_seconds
        self._lead_minutes = lead_minutes
        self._now = now  # injectable for deterministic tests
        self.enabled = enabled  # config sets the boot state; the skill flips it
        # While standing down, polls are skipped (no fetch, no announcements).
        self._standdown = standdown or StandDown()
        self._revoicer = revoicer

    async def run(self) -> None:
        log.info(
            "Calendar watcher started (poll=%.0fs, lead=%dmin, enabled=%s)",
            self._poll_seconds, self._lead_minutes, self.enabled,
        )
        while True:
            if self.enabled and not self._standdown.active:
                try:
                    await self._poll()
                except Exception as exc:  # noqa: BLE001 - one failure must not kill the loop
                    log.warning("Calendar watch poll failed: %s", exc)
            await asyncio.sleep(self._poll_seconds)

    async def _poll(self) -> None:
        now = self._now()
        window_end = now + timedelta(minutes=self._lead_minutes)
        events = []
        for calendar_id in self._calendar_ids:
            events.extend(
                await self._provider.list_events(calendar_id, time_min=now, time_max=window_end)
            )
        events.sort(key=lambda e: e.start)
        for event in events:
            if event.all_day:  # "in N minutes" is meaningless for an all-day event
                continue
            if self._blocklist.is_blocked(event):
                continue
            if self._state.was_announced(event.id, event.start.timestamp()):
                continue
            await self._announce(event, now)
        self._state.purge_before(now.timestamp() - _PURGE_AFTER_S)

    async def _announce(self, event, now: datetime) -> None:
        minutes = max(0, round((event.start - now).total_seconds() / 60))
        title = speakable_title(event.title)
        if minutes == 0:
            text = f"You have {title} now."
        else:
            text = f"You have {title} in {minutes} minute{'' if minutes == 1 else 's'}."
        try:
            log.info("Calendar announcement: %r", text)
            if self._revoicer is not None:
                text = await self._revoicer.revoice(text)
            async with self._arbiter.hold("calendar"):
                await self._audio_out.play(await self._tts.synthesize(text))
        except Exception as exc:  # noqa: BLE001 - unmarked, so the next poll retries
            log.error("Failed to announce event %s: %s", event.id, exc)
        else:
            self._state.mark(event.id, event.start.timestamp(), announced_at=now.timestamp())
