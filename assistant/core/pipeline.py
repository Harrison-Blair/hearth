"""Voice pipeline orchestrator.

Phase 3: the first full slice. Listen for the wake word, record the utterance,
transcribe it, route to a skill, and speak the skill's reply.
"""

from __future__ import annotations

import asyncio
import logging
import random
import re
from collections import deque

import numpy as np

from assistant.audio.base import AudioIn, AudioOut
from assistant.audio.processing import normalize_peak
from assistant.audio.recorder import VadRecorder
from assistant.core.arbiter import AudioArbiter
from assistant.core.conversation import Conversation
from assistant.core.events import Command, WakeEvent
from assistant.core.orchestrator import Orchestrator
from assistant.core.state import NullStateEmitter
from assistant.stt.base import SpeechToText
from assistant.tts.base import TextToSpeech
from assistant.wake.base import WakeDetector

log = logging.getLogger(__name__)

# Split on sentence-final punctuation followed by whitespace/end (so "3.14" and
# "e.g." mid-word stay intact), keeping the punctuation with its sentence.
_SENTENCE_RE = re.compile(r".+?(?:[.!?]+(?=\s|$)|$)", re.S)


def _split_sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_RE.findall(text) if s.strip()]


class VoicePipeline:
    def __init__(
        self,
        audio_in: AudioIn,
        detector: WakeDetector,
        recorder: VadRecorder,
        stt: SpeechToText,
        orchestrator: Orchestrator,
        tts: TextToSpeech,
        audio_out: AudioOut,
        arbiter: AudioArbiter,
        preroll_frames: int = 6,
        sample_rate: int = 16000,
        no_speech_earcon: bytes = b"",
        wake_earcons: list[bytes] | None = None,
        end_earcon: bytes = b"",
        normalize: bool = False,
        normalize_target_peak: float = 0.97,
        normalize_rms_floor: float = 200.0,
        min_transcribe_rms: float = 0.0,
        conversation_enabled: bool = True,
        followup_window_ms: int = 6000,
        max_history_turns: int = 12,
        state_emitter=None,
    ) -> None:
        self._audio_in = audio_in
        self._detector = detector
        self._recorder = recorder
        self._stt = stt
        self._orchestrator = orchestrator
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
        # Played the moment the wake word is detected (a spoken acknowledgement,
        # e.g. "hmm?"/"uh huh?"), so the user knows the device is listening. One is
        # chosen at random per wake for variety. Empty list -> no cue (e.g. in tests).
        self._wake_earcons = wake_earcons or []
        # Soft descending cue played the instant recording ends, so the user knows
        # the mic has closed and we've moved on to thinking. Empty -> none.
        self._end_earcon = end_earcon
        # Optional peak normalization of the utterance before STT, to compensate
        # for a quiet or hot mic. Gated by RMS so silence isn't amplified.
        self._normalize = normalize
        self._normalize_target_peak = normalize_target_peak
        self._normalize_rms_floor = normalize_rms_floor
        # Below this int16 RMS a capture is treated as silence and never sent to
        # STT — whisper invents text on near-silent audio. 0.0 = disabled.
        self._min_transcribe_rms = min_transcribe_rms
        # After the assistant speaks, keep listening for a follow-up (no wake word)
        # until this window of silence elapses, then the conversation ends.
        self._conversation_enabled = conversation_enabled
        self._followup_window_ms = followup_window_ms
        self._max_history_turns = max_history_turns
        # One rolling history for the typed (TUI chat) session, so daemon-lifetime
        # typed turns carry context. Disabled -> each typed turn is stateless.
        self._typed_conversation = Conversation(max_history_turns)
        # Surfaces turn state (idle/listening/thinking/speaking) and mic level to
        # the monitor TUI. Null by default (standalone daemon / tests).
        self._state_emitter = state_emitter or NullStateEmitter()
        # Touch affordances from the TUI (over the control channel): request a turn
        # without the wake word, and abandon the current capture. Set from another
        # task; consumed in the run loop / recorder.
        self._listen_event = asyncio.Event()
        self._cancel_event = asyncio.Event()

    def request_listen(self) -> None:
        """Start a turn now, skipping the wake word (tap-to-listen). No-op if a
        turn is already under way — the loop only reads this between turns."""
        self._listen_event.set()

    def cancel(self) -> None:
        """Abandon the current capture and cut off any playback (tap-to-cancel /
        barge-in). The recorder returns empty and the turn ends."""
        self._cancel_event.set()
        self._audio_out.stop()

    async def run(self) -> None:
        frames = self._audio_in.stream()
        preroll: deque[bytes] = deque(maxlen=self._preroll_frames)
        was_busy = False
        self._state_emitter.state("idle")
        log.info("Listening for wake word...")
        async for frame in frames:
            # A proactive announcement (a reminder) is playing: don't feed its
            # audio to the wake detector or it could self-trigger. Keep draining
            # the mic queue so it doesn't back up.
            if self._arbiter.busy:
                preroll.clear()
                if not was_busy:
                    # Drop the detector's rolling window on the way into busy, so
                    # audio from before the announcement can't splice with audio
                    # after it into a phantom wake once it ends.
                    self._detector.reset()
                    was_busy = True
                continue
            was_busy = False

            preroll.append(frame)
            event = self._detector.process(frame)
            if event is None:
                if self._listen_event.is_set():
                    self._listen_event.clear()
                    log.info("Manual listen requested (tap-to-listen)")
                    event = WakeEvent(name="manual", score=1.0)
                else:
                    continue
            else:
                log.info("Wake word detected: %s (%.2f)", event.name, event.score)
            # Own the audio device for the whole turn so a reminder can't play
            # over the capture or our reply; it waits until we release.
            async with self._arbiter.hold("pipeline"):
                pcm = await self._listen(frames, prefix=b"".join(preroll))
                preroll.clear()
                transcript = await self._capture_to_text(pcm)
                if not transcript:
                    # A beat too slow to start: reopen the mic exactly once, using
                    # the follow-up window, so the user can just repeat without
                    # re-waking. One retry only, never a loop.
                    pcm = await self._listen(frames, start_timeout_ms=self._followup_window_ms)
                    transcript = await self._capture_to_text(pcm)
                if transcript:
                    log.info("Heard: %r", transcript)
                    self._state_emitter.state("thinking", transcript=transcript)
                    await self._converse(frames, transcript)
                else:
                    log.info("No speech captured.")
                    self._state_emitter.state("no_speech")
                    if self._no_speech_earcon:
                        await self._play(self._no_speech_earcon)

            self._state_emitter.state("idle")

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
        conv = (
            self._typed_conversation
            if self._conversation_enabled
            else Conversation(self._max_history_turns)
        )
        async with self._arbiter.hold("text"):
            result, _ = await self._handle(text, conv, spoken=False)
            if result is not None and result.expects_reply:
                log.warning("Typed turn requested a reply; ignored (no audio path)")

    async def _converse(self, frames, transcript: str) -> None:
        """Run one conversation: the initial turn plus follow-ups captured without
        a new wake word, until silence (or a disabled conversation) closes it."""
        conv = Conversation(self._max_history_turns)
        reply_skill = None
        while True:
            if reply_skill is not None:
                result = await self._dispatch_reply(reply_skill, transcript, conv)
                reply_skill = None
                if result is not None and result.expects_reply:
                    log.warning("Reply result set expects_reply; ignored (one round only)")
            else:
                result, skill = await self._handle(transcript, conv, spoken=True)
                if result is not None and result.expects_reply and skill is not None:
                    reply_skill = skill
            if reply_skill is None and not self._conversation_enabled:
                return
            transcript = await self._capture_followup(frames)
            if not transcript:
                if reply_skill is not None:
                    # Silence during a pending reply: deliver it as a cancel.
                    await self._dispatch_reply(reply_skill, "", conv)
                return

    async def _capture_followup(self, frames):
        pcm = await self._listen(frames, start_timeout_ms=self._followup_window_ms)
        return await self._capture_to_text(pcm)

    async def _listen(self, frames, *, prefix: bytes = b"", start_timeout_ms=None) -> bytes:
        """One listening window: play the mic-open cue (a random acknowledgement),
        drop its echo, record until end-of-speech, then play the mic-closed cue.
        Returns raw PCM.

        The open cue doubles as the follow-up "mic open" prompt. Draining after it
        keeps the cue's own speaker bleed out of the recording."""
        self._cancel_event.clear()  # a cancel only abandons the turn it arrives in
        if self._wake_earcons:
            await self._play(random.choice(self._wake_earcons))
        self._audio_in.drain()
        self._state_emitter.state("listening")
        pcm = await self._recorder.record(
            frames,
            prefix=prefix,
            start_timeout_ms=start_timeout_ms,
            on_level=self._state_emitter.level,
            cancel_event=self._cancel_event,
        )
        self._state_emitter.state("thinking")
        if self._end_earcon:
            await self._play(self._end_earcon)
        return pcm

    async def _capture_to_text(self, pcm: bytes) -> str:
        """Log the capture, drop near-silence before STT (whisper hallucinates on
        it), optionally peak-normalize, then transcribe."""
        rms = self._log_capture(pcm)
        if self._min_transcribe_rms and rms < self._min_transcribe_rms:
            log.info(
                "Capture rms=%.0f below transcribe floor %.0f; treating as silence",
                rms,
                self._min_transcribe_rms,
            )
            return ""
        if self._normalize:
            pcm = normalize_peak(pcm, self._normalize_target_peak, self._normalize_rms_floor)
        return await self._stt.transcribe(pcm)

    async def _handle(self, transcript, conv, *, spoken):
        try:
            result, skill = await self._orchestrator.handle(
                transcript, conv.history(), spoken=spoken
            )
        except Exception as exc:  # noqa: BLE001 - a skill/LLM crash must not kill the loop
            log.error("Orchestration failed: %s", exc)
            self._state_emitter.state("error", message="Something went wrong.")
            await self._speak("Sorry, something went wrong.")
            return None, None
        if result is None:
            log.warning("Nothing could handle %r", transcript)
            await self._speak("Sorry, I can't help with that yet.")
            return None, None
        log.info("Reply: %r", result.speech)
        await self._speak(result.speech)
        conv.add("user", transcript)
        if result.speech:
            conv.add("assistant", result.speech)
        return result, skill

    async def _dispatch_reply(self, skill, transcript, conv):
        log.info("Routing reply to skill %r", skill.name)
        try:
            result = await skill.handle_reply(Command(transcript, history=conv.history()))
        except Exception as exc:  # noqa: BLE001 - a skill crash must not kill the loop
            log.error("Skill %r reply failed: %s", skill.name, exc)
            await self._speak("Sorry, something went wrong.")
            return None
        log.info("Reply: %r", result.speech)
        await self._speak(result.speech)
        if transcript:
            conv.add("user", transcript)
        if result.speech:
            conv.add("assistant", result.speech)
        return result

    async def _speak(self, text: str) -> None:
        # Synthesize and play sentence by sentence so the first audio starts before
        # the whole reply is synthesized, cutting the "wait for the full synth" stall.
        self._state_emitter.state("speaking", text=text)
        try:
            for sentence in _split_sentences(text):
                await self._play(await self._tts.synthesize(sentence))
        except Exception as exc:  # noqa: BLE001 - a synth/playback error must not kill the loop
            log.error("Speak failed: %s", exc)

    async def _play(self, audio: bytes) -> None:
        # Output failures (device unplugged, PortAudio error) must not escape the
        # wake loop; a raised exception there would leave the assistant deaf.
        try:
            await self._audio_out.play(audio)
        except Exception as exc:  # noqa: BLE001 - playback error must not kill the loop
            log.error("Playback failed: %s", exc)

    def _log_capture(self, pcm: bytes) -> float:
        samples = np.frombuffer(pcm, dtype=np.int16)
        if not len(samples):
            log.info("Captured 0.0s (silence)")
            return 0.0
        rms = float(np.sqrt(np.mean(samples.astype(np.float32) ** 2)))
        log.info(
            "Captured %.1fs (rms=%.0f, peak=%d)",
            len(samples) / self._sample_rate,
            rms,
            int(np.abs(samples).max()),
        )
        return rms
