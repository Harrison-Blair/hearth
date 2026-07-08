"""Mid-turn speech helper.

Lets a skill speak progress lines while its handle() is still running (the skill
already owns the audio device: the pipeline holds the arbiter for the whole
turn). Mirrors ReminderScheduler's direct tts+out use. Errors never escape — a
progress line is decoration, not a result.
"""

from __future__ import annotations

import logging

from assistant.audio.base import AudioOut
from assistant.tts.base import TextToSpeech

log = logging.getLogger(__name__)


class Speaker:
    def __init__(self, tts: TextToSpeech, audio_out: AudioOut) -> None:
        self._tts = tts
        self._out = audio_out

    async def say(self, text: str, length_scale: float | None = None) -> None:
        try:
            await self._out.play(await self._tts.synthesize(text, length_scale=length_scale))
        except Exception as exc:  # noqa: BLE001 - progress speech must never break the turn
            log.error("Progress speech failed: %s", exc)
