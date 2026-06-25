"""Voice pipeline orchestrator.

Phase 3: the first full slice. Listen for the wake word, record the utterance,
transcribe it, route to a skill, and speak the skill's reply.
"""

from __future__ import annotations

import logging
from collections import deque

import numpy as np

from assistant.audio.base import AudioIn, AudioOut
from assistant.audio.recorder import VadRecorder
from assistant.core.events import Command
from assistant.nlu.router import IntentRouter
from assistant.skills.base import SkillRegistry
from assistant.stt.base import SpeechToText
from assistant.tts.base import TextToSpeech
from assistant.wake.base import WakeDetector

log = logging.getLogger(__name__)

# ~0.5s of 80ms frames kept before the wake event, so a command spoken
# immediately after the wake word (clipped by detection latency) is recovered.
_PREROLL_FRAMES = 6


class VoicePipeline:
    def __init__(
        self,
        audio_in: AudioIn,
        detector: WakeDetector,
        recorder: VadRecorder,
        stt: SpeechToText,
        router: IntentRouter,
        registry: SkillRegistry,
        tts: TextToSpeech,
        audio_out: AudioOut,
    ) -> None:
        self._audio_in = audio_in
        self._detector = detector
        self._recorder = recorder
        self._stt = stt
        self._router = router
        self._registry = registry
        self._tts = tts
        self._audio_out = audio_out

    async def run(self) -> None:
        frames = self._audio_in.stream()
        preroll: deque[bytes] = deque(maxlen=_PREROLL_FRAMES)
        log.info("Listening for wake word...")
        async for frame in frames:
            preroll.append(frame)
            event = self._detector.process(frame)
            if event is None:
                continue

            log.info("Wake word detected: %s (%.2f)", event.name, event.score)
            pcm = await self._recorder.record(frames, prefix=b"".join(preroll))
            preroll.clear()
            self._log_capture(pcm)

            transcript = await self._stt.transcribe(pcm)
            if transcript:
                log.info("Heard: %r", transcript)
                await self._handle(transcript)
            else:
                log.info("No speech captured.")

            self._detector.reset()
            log.info("Listening for wake word...")

    async def _handle(self, transcript: str) -> None:
        intent = await self._router.route(transcript)
        skill = self._registry.get(intent.type)
        if skill is None:
            log.warning("No skill registered for intent %r", intent.type)
            await self._speak("Sorry, I can't help with that yet.")
            return

        log.info("Routing to skill %r (intent=%s)", skill.name, intent.type)
        result = await skill.handle(Command(transcript), intent)
        log.info("Reply: %r", result.speech)
        await self._speak(result.speech)

    async def _speak(self, text: str) -> None:
        audio = await self._tts.synthesize(text)
        await self._audio_out.play(audio)

    @staticmethod
    def _log_capture(pcm: bytes) -> None:
        samples = np.frombuffer(pcm, dtype=np.int16)
        if not len(samples):
            log.info("Captured 0.0s (silence)")
            return
        rms = float(np.sqrt(np.mean(samples.astype(np.float32) ** 2)))
        log.info(
            "Captured %.1fs (rms=%.0f, peak=%d)",
            len(samples) / 16000,
            rms,
            int(np.abs(samples).max()),
        )
