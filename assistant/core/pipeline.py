"""Voice pipeline orchestrator.

Phase 3: the first full slice. Listen for the wake word, record the utterance,
transcribe it, route to a skill, and speak the skill's reply.
"""

from __future__ import annotations

import logging
from collections import deque

import numpy as np

from assistant.audio.base import AudioIn, AudioOut
from assistant.audio.processing import normalize_peak
from assistant.audio.recorder import VadRecorder
from assistant.core.arbiter import AudioArbiter
from assistant.core.events import Command
from assistant.nlu.router import IntentRouter
from assistant.skills.base import SkillRegistry
from assistant.stt.base import SpeechToText
from assistant.tts.base import TextToSpeech
from assistant.wake.base import WakeDetector

log = logging.getLogger(__name__)


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
        arbiter: AudioArbiter,
        preroll_frames: int = 6,
        sample_rate: int = 16000,
        no_speech_earcon: bytes = b"",
        wake_earcon: bytes = b"",
        normalize: bool = False,
        normalize_target_peak: float = 0.97,
        normalize_rms_floor: float = 200.0,
    ) -> None:
        self._audio_in = audio_in
        self._detector = detector
        self._recorder = recorder
        self._stt = stt
        self._router = router
        self._registry = registry
        self._tts = tts
        self._audio_out = audio_out
        self._arbiter = arbiter
        # ~0.5s of frames kept before the wake event, so a command spoken
        # immediately after the wake word (clipped by detection latency) is recovered.
        self._preroll_frames = preroll_frames
        self._sample_rate = sample_rate
        # Short blip played when we wake but hear nothing, so the user gets
        # feedback instead of silence. Empty -> no earcon (e.g. in tests).
        self._no_speech_earcon = no_speech_earcon
        # Ding played the moment the wake word is detected, so the user knows
        # the device is listening. Empty -> no earcon (e.g. in tests).
        self._wake_earcon = wake_earcon
        # Optional peak normalization of the utterance before STT, to compensate
        # for a quiet or hot mic. Gated by RMS so silence isn't amplified.
        self._normalize = normalize
        self._normalize_target_peak = normalize_target_peak
        self._normalize_rms_floor = normalize_rms_floor

    async def run(self) -> None:
        frames = self._audio_in.stream()
        preroll: deque[bytes] = deque(maxlen=self._preroll_frames)
        log.info("Listening for wake word...")
        async for frame in frames:
            # A proactive announcement (a reminder) is playing: don't feed its
            # audio to the wake detector or it could self-trigger. Keep draining
            # the mic queue so it doesn't back up.
            if self._arbiter.busy:
                preroll.clear()
                continue

            preroll.append(frame)
            event = self._detector.process(frame)
            if event is None:
                continue

            log.info("Wake word detected: %s (%.2f)", event.name, event.score)
            # Own the audio device for the whole turn so a reminder can't play
            # over the capture or our reply; it waits until we release.
            async with self._arbiter.hold("pipeline"):
                if self._wake_earcon:
                    await self._play(self._wake_earcon)
                pcm = await self._recorder.record(frames, prefix=b"".join(preroll))
                preroll.clear()
                self._log_capture(pcm)
                if self._normalize:
                    pcm = normalize_peak(
                        pcm, self._normalize_target_peak, self._normalize_rms_floor
                    )

                transcript = await self._stt.transcribe(pcm)
                if transcript:
                    log.info("Heard: %r", transcript)
                    await self._handle(transcript)
                else:
                    log.info("No speech captured.")
                    if self._no_speech_earcon:
                        await self._play(self._no_speech_earcon)

            self._detector.reset()
            log.info("Listening for wake word...")

    async def submit_text(self, text: str) -> None:
        """Inject a typed command as if it had been transcribed from speech.

        Used by the control channel (the monitor TUI's chat box). Runs the same
        route -> skill -> speak path as a spoken turn, and holds the arbiter so a
        typed turn can't collide with wake capture or a reminder announcement.
        """
        text = text.strip()
        if not text:
            return
        log.info("Heard (typed): %r", text)
        async with self._arbiter.hold("text"):
            await self._handle(text)

    async def _handle(self, transcript: str) -> None:
        intent = await self._router.route(transcript)
        skill = self._registry.get(intent.type)
        if skill is None:
            log.warning("No skill registered for intent %r", intent.type)
            await self._speak("Sorry, I can't help with that yet.")
            return

        log.info("Routing to skill %r (intent=%s)", skill.name, intent.type)
        try:
            result = await skill.handle(Command(transcript), intent)
        except Exception as exc:  # noqa: BLE001 - a skill crash must not kill the loop
            log.error("Skill %r failed: %s", skill.name, exc)
            await self._speak("Sorry, something went wrong.")
            return
        log.info("Reply: %r", result.speech)
        await self._speak(result.speech)

    async def _speak(self, text: str) -> None:
        try:
            await self._play(await self._tts.synthesize(text))
        except Exception as exc:  # noqa: BLE001 - a synth/playback error must not kill the loop
            log.error("Speak failed: %s", exc)

    async def _play(self, audio: bytes) -> None:
        # Output failures (device unplugged, PortAudio error) must not escape the
        # wake loop; a raised exception there would leave the assistant deaf.
        try:
            await self._audio_out.play(audio)
        except Exception as exc:  # noqa: BLE001 - playback error must not kill the loop
            log.error("Playback failed: %s", exc)

    def _log_capture(self, pcm: bytes) -> None:
        samples = np.frombuffer(pcm, dtype=np.int16)
        if not len(samples):
            log.info("Captured 0.0s (silence)")
            return
        rms = float(np.sqrt(np.mean(samples.astype(np.float32) ** 2)))
        log.info(
            "Captured %.1fs (rms=%.0f, peak=%d)",
            len(samples) / self._sample_rate,
            rms,
            int(np.abs(samples).max()),
        )
