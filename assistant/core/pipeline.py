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
from assistant.core.events import Command, Turn, WakeEvent
from assistant.core.orchestrator import Orchestrator
from assistant.core.state import NullStateEmitter
from assistant.llm.base import LLMProvider
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
        llm: LLMProvider | None = None,
        followup_cue_enabled: bool = False,
        followup_cue_timeout_s: float = 4.0,
        followup_cue_prompt: str = "",
        signoff_enabled: bool = False,
        signoff_timeout_s: float = 4.0,
        signoff_pause_s: float = 0.0,
        signoff_prompt: str = "",
        end_phrases: list[str] | None = None,
        ack_delay_s: float = 0.0,
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
        # Context-aware spoken cues, generated live from the conversation history.
        # Both need an LLM; without one (tests / no-LLM deploy) they no-op. The
        # follow-up cue replaces the nonsensical repeated wake ack at a follow-up
        # mic-open; the sign-off gives an explicitly-ended conversation a spoken
        # close. Both degrade to silence on LLM timeout/failure, so the offline
        # path is unchanged.
        self._llm = llm
        self._followup_cue_enabled = followup_cue_enabled
        self._followup_cue_timeout_s = followup_cue_timeout_s
        self._followup_cue_prompt = followup_cue_prompt
        self._signoff_enabled = signoff_enabled
        self._signoff_timeout_s = signoff_timeout_s
        self._signoff_pause_s = signoff_pause_s
        self._signoff_prompt = signoff_prompt
        # Normalized set of utterances that explicitly close a conversation.
        self._end_phrases = [self._normalize_text(p) for p in (end_phrases or [])]
        # Beat of silence before the wake ack plays, so "hmm?" isn't instant.
        self._ack_delay_s = ack_delay_s
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
                if not self._listen_event.is_set():
                    continue
                log.info("Manual listen requested (tap-to-listen)")
                event = WakeEvent(name="manual", score=1.0)
            else:
                log.info("Wake word detected: %s (%.2f)", event.name, event.score)
            self._listen_event.clear()  # consumed either way; a real wake clears a racing tap
            # Own the audio device for the whole turn so a reminder can't play
            # over the capture or our reply; it waits until we release.
            async with self._arbiter.hold("pipeline"):
                pcm = await self._listen(
                    frames,
                    prefix=b"".join(preroll),
                    open_cue=self._pick_wake_ack(),
                    open_delay_s=self._ack_delay_s,
                )
                preroll.clear()
                transcript = await self._capture_to_text(pcm)
                if not transcript:
                    # A beat too slow to start: reopen the mic exactly once, using
                    # the follow-up window, so the user can just repeat without
                    # re-waking. One retry only, never a loop.
                    pcm = await self._listen(
                        frames,
                        start_timeout_ms=self._followup_window_ms,
                        open_cue=self._pick_wake_ack(),
                        open_delay_s=self._ack_delay_s,
                    )
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
            # A context-aware follow-up cue, generated while the reply is spoken so
            # it's ready by the time the follow-up mic opens (no added mic latency).
            cue_task: asyncio.Task | None = None

            def start_cue(result, transcript=transcript):
                nonlocal cue_task
                if self._followup_cue_enabled and self._llm is not None and result.speech:
                    turns = conv.history() + [
                        Turn("user", transcript),
                        Turn("assistant", result.speech),
                    ]
                    cue_task = asyncio.create_task(self._make_cue(turns))

            if reply_skill is not None:
                result = await self._dispatch_reply(
                    reply_skill, transcript, conv, on_reply=start_cue
                )
                reply_skill = None
                if result is not None and result.expects_reply:
                    log.warning("Reply result set expects_reply; ignored (one round only)")
            else:
                result, skill = await self._handle(
                    transcript, conv, spoken=True, on_reply=start_cue
                )
                if result is not None and result.expects_reply and skill is not None:
                    reply_skill = skill
            if reply_skill is None and not self._conversation_enabled:
                self._drop_cue(cue_task)
                return
            open_cue = await self._collect_cue(cue_task)
            transcript = await self._capture_followup(frames, open_cue=open_cue)
            if not transcript:
                # Silence closes the conversation quietly — the descending tone at
                # mic-close already signalled the end; no spoken farewell.
                if reply_skill is not None:
                    # Silence during a pending reply: deliver it as a cancel.
                    await self._dispatch_reply(reply_skill, "", conv)
                return
            if reply_skill is None and self._is_end_phrase(transcript):
                # The user explicitly ended the conversation ("goodbye" / "I'm
                # done"): speak a context-aware farewell instead of routing it.
                await self._maybe_signoff(conv)
                return
            # A follow-up walks through _listen (listening -> thinking) with no
            # transcript; re-emit thinking with the heard text so the TUI's "you
            # said" line fills for follow-ups too, not just the first turn.
            self._state_emitter.state("thinking", transcript=transcript)

    async def _capture_followup(self, frames, open_cue: bytes | None = None):
        pcm = await self._listen(
            frames, start_timeout_ms=self._followup_window_ms, open_cue=open_cue
        )
        return await self._capture_to_text(pcm)

    def _pick_wake_ack(self) -> bytes | None:
        """A random pre-cached wake acknowledgement ("hmm?"), or None if the pool
        is empty (e.g. tests)."""
        return random.choice(self._wake_earcons) if self._wake_earcons else None

    async def _listen(
        self,
        frames,
        *,
        prefix: bytes = b"",
        start_timeout_ms=None,
        open_cue: bytes | None = None,
        open_delay_s: float = 0.0,
    ) -> bytes:
        """One listening window: play the caller's mic-open cue, drop its echo,
        record until end-of-speech, then play the mic-closed cue. Returns raw PCM.

        The caller chooses the open cue (a wake ack on first wake, a context-aware
        cue on a follow-up, or None) and an optional delay before it (a beat before
        the wake ack). Draining after it keeps the cue's own speaker bleed out of
        the recording."""
        self._cancel_event.clear()  # a cancel only abandons the turn it arrives in
        if open_cue:
            if open_delay_s:
                await asyncio.sleep(open_delay_s)
            await self._play(open_cue)
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

    async def _handle(self, transcript, conv, *, spoken, on_reply=None):
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
        if on_reply is not None:
            on_reply(result)  # kick off cue generation to overlap with playback
        await self._speak(result.speech)
        conv.add("user", transcript)
        if result.speech:
            conv.add("assistant", result.speech)
        return result, skill

    async def _dispatch_reply(self, skill, transcript, conv, on_reply=None):
        log.info("Routing reply to skill %r", skill.name)
        try:
            result = await skill.handle_reply(Command(transcript, history=conv.history()))
        except Exception as exc:  # noqa: BLE001 - a skill crash must not kill the loop
            log.error("Skill %r reply failed: %s", skill.name, exc)
            await self._speak("Sorry, something went wrong.")
            return None
        log.info("Reply: %r", result.speech)
        if on_reply is not None:
            on_reply(result)  # kick off cue generation to overlap with playback
        await self._speak(result.speech)
        if transcript:
            conv.add("user", transcript)
        if result.speech:
            conv.add("assistant", result.speech)
        return result

    async def _make_cue(self, history: list[Turn]) -> bytes | None:
        """Generate and synthesize a short context-aware follow-up cue. Returns the
        cue PCM, or None on empty output / any LLM or TTS failure (silent reopen)."""
        try:
            text = await self._llm.complete(
                self._render_history(history), system=self._followup_cue_prompt, label="cue"
            )
        except Exception as exc:  # noqa: BLE001 - LLM failure must degrade to a silent reopen
            log.warning("Follow-up cue generation failed: %s", exc)
            return None
        text = text.strip()
        if not text:
            return None
        try:
            return await self._tts.synthesize(text)
        except Exception as exc:  # noqa: BLE001 - synth failure must degrade to a silent reopen
            log.warning("Follow-up cue synthesis failed: %s", exc)
            return None

    async def _collect_cue(self, cue_task) -> bytes | None:
        """Await the pending cue up to its budget so it never delays mic-open;
        drop it (silent reopen) if it isn't ready in time."""
        if cue_task is None:
            return None
        try:
            return await asyncio.wait_for(cue_task, self._followup_cue_timeout_s)
        except TimeoutError:
            log.info(
                "Follow-up cue not ready in %.1fs; opening mic silently",
                self._followup_cue_timeout_s,
            )
            cue_task.cancel()
            return None
        except Exception as exc:  # noqa: BLE001 - never block the loop on the cue
            log.warning("Follow-up cue failed: %s", exc)
            return None

    @staticmethod
    def _drop_cue(cue_task) -> None:
        if cue_task is not None:
            cue_task.cancel()

    async def _maybe_signoff(self, conv) -> None:
        """Speak a short context-aware farewell when the user explicitly ends the
        conversation. No-op (silent) without an LLM or on timeout/failure."""
        if not (self._signoff_enabled and self._llm is not None):
            return
        try:
            text = await asyncio.wait_for(
                self._llm.complete(
                    self._render_history(conv.history()),
                    system=self._signoff_prompt,
                    label="signoff",
                ),
                self._signoff_timeout_s,
            )
        except TimeoutError:
            log.info("Sign-off not ready in %.1fs; ending silently", self._signoff_timeout_s)
            return
        except Exception as exc:  # noqa: BLE001 - never block the ending on the LLM
            log.warning("Sign-off generation failed: %s", exc)
            return
        text = text.strip()
        if text:
            if self._signoff_pause_s:
                await asyncio.sleep(self._signoff_pause_s)  # a breath before the farewell
            await self._speak(text)

    @staticmethod
    def _render_history(history: list[Turn]) -> str:
        return "\n".join(f"{t.role.capitalize()}: {t.content}" for t in history)

    @staticmethod
    def _normalize_text(text: str) -> str:
        """Lowercase and strip to alphanumerics + single spaces, so end-phrase
        matching ignores punctuation and casing from the transcript."""
        return " ".join("".join(c if c.isalnum() else " " for c in text.lower()).split())

    def _is_end_phrase(self, transcript: str) -> bool:
        norm = self._normalize_text(transcript)
        return any(phrase in norm for phrase in self._end_phrases)

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
