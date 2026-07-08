"""Voice pipeline orchestrator.

Phase 3: the first full slice. Listen for the wake word, record the utterance,
transcribe it, route to a skill, and speak the skill's reply.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import re
from collections import deque
from typing import Callable

import numpy as np

from assistant.audio.base import AudioIn, AudioOut
from assistant.audio.processing import normalize_peak
from assistant.audio.recorder import VadRecorder
from assistant.core.arbiter import AudioArbiter
from assistant.core.conversation import Conversation
from assistant.core.events import Command, Turn, WakeEvent
from assistant.core.orchestrator import Orchestrator
from assistant.core.persona import canned
from assistant.core.revoice import Revoicer
from assistant.core.selfupdate import restart_in_place as _default_restart_in_place
from assistant.core.standdown import StandDown
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


class _BargeGate:
    """Consecutive-events gate on top of the wake detector's own debounce: a
    barge needs ``trigger`` events at or above ``threshold`` in a row; an event
    below the raised bar (speaker echo grazing the wake threshold) resets the
    streak. ``None`` offers (window filling / under the wake threshold) are not
    a verdict and leave the streak alone."""

    def __init__(self, threshold: float, trigger: int) -> None:
        self._threshold = threshold
        self._trigger = max(1, trigger)
        self._streak = 0

    def offer(self, event: WakeEvent | None) -> bool:
        if event is None:
            return False
        if event.score < self._threshold:
            self._streak = 0
            return False
        self._streak += 1
        if self._streak < self._trigger:
            return False
        self._streak = 0
        return True

    def reset(self) -> None:
        self._streak = 0


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
        unsure_wake_earcons: list[bytes] | None = None,
        wake_confident_threshold: float = 0.0,
        end_earcon: bytes = b"",
        normalize: bool = False,
        normalize_target_peak: float = 0.97,
        normalize_rms_floor: float = 200.0,
        min_transcribe_rms: float = 0.0,
        hallucination_phrases: list[str] | None = None,
        hallucination_max_rms: float = 0.0,
        conversation_enabled: bool = True,
        followup_window_ms: int = 6000,
        max_history_turns: int = 12,
        llm: LLMProvider | None = None,
        decision_enabled: bool = False,
        decision_timeout_s: float = 4.0,
        decision_prompt: str = "",
        decline_phrases: list[str] | None = None,
        confirm_earcon: bytes = b"",
        end_phrases: list[str] | None = None,
        ack_delay_s: float = 0.0,
        state_emitter=None,
        standdown: StandDown | None = None,
        barge_in_enabled: bool = False,
        barge_in_threshold: float = 0.8,
        barge_in_trigger_frames: int = 3,
        barge_in_announcements: bool = False,
        restart_in_place: Callable[[], None] | None = None,
        revoicer: Revoicer | None = None,
        persona_enabled: bool = False,
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
        # e.g. "Hello!"), so the user knows the device is listening. One is
        # chosen at random per wake for variety. Empty list -> no cue (e.g. in tests).
        self._wake_earcons = wake_earcons or []
        # Spoken instead when the wake score falls below the confident threshold
        # ("Did you say something?"), signalling an uncertain pickup. Empty ->
        # every wake uses the confident pool.
        self._unsure_wake_earcons = unsure_wake_earcons or []
        self._wake_confident_threshold = wake_confident_threshold
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
        # Known whisper hallucinations ("thank you", YouTube outros). A low-energy
        # capture whose whole transcript is only these phrases is treated as
        # silence; loud captures pass through untouched. Kept as normalized token
        # sequences, longest first, so repetitions match greedily.
        self._hallucination_phrases = sorted(
            (
                tokens
                for p in (hallucination_phrases or [])
                if (tokens := self._normalize_text(p).split())
            ),
            key=len,
            reverse=True,
        )
        self._hallucination_max_rms = hallucination_max_rms
        # After the assistant speaks, keep listening for a follow-up (no wake word)
        # until this window of silence elapses, then the conversation ends.
        self._conversation_enabled = conversation_enabled
        self._followup_window_ms = followup_window_ms
        self._max_history_turns = max_history_turns
        # Context-aware continuation: after each completed reply an LLM decides
        # whether to keep listening (the reply asked a question), check in once
        # (a soft earcon at mic-open), or end the conversation. Needs an LLM;
        # without one (tests / no-LLM deploy) it no-ops, and it degrades to the
        # plain silence-closed follow-up loop on LLM timeout/failure, so the
        # offline path is unchanged.
        self._llm = llm
        self._decision_enabled = decision_enabled
        self._decision_timeout_s = decision_timeout_s
        self._decision_prompt = decision_prompt
        # Normalized exact-match declines ("no", "that's it") that end the
        # conversation, honored only on the turn right after a check-in.
        self._decline_phrases = {self._normalize_text(p) for p in (decline_phrases or [])}
        # Soft cue played at the follow-up mic-open after a "confirm" decision,
        # so the user knows the assistant is still listening. Empty -> silent
        # reopen (e.g. in tests).
        self._confirm_earcon = confirm_earcon
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
        # Shared "stand down" state: while active, wake detection is suspended
        # (the stand-down skill engages it; the TUI's Resume button or a deadline
        # clears it). Own instance by default so tests/wiring without it still work.
        self._standdown = standdown or StandDown()
        # Barge-in: while a reply plays, a mic tap (AudioIn.set_tap) keeps scoring
        # the wake word; a hit cuts playback and reopens the mic. The raised
        # threshold + consecutive-event gate sit on top of the detector's own
        # debounce so residual speaker echo can't self-trigger as easily.
        self._barge_in_enabled = barge_in_enabled
        self._barge_in_threshold = barge_in_threshold
        self._barge_in_trigger_frames = max(1, barge_in_trigger_frames)
        self._barge_in_announcements = barge_in_announcements
        self._barged = False  # set by _speak, consumed by _converse
        # Self-update: re-execs the daemon after a sign-off is spoken. Injectable
        # so tests never invoke the real os.execv; defaults to the real primitive.
        self._restart_in_place = restart_in_place or _default_restart_in_place
        # Restyles a not-already-persona'd reply in the persona's voice at the top
        # of _speak, before sentence splitting/TTS. None (persona off, or no LLM
        # wired) -> passthrough, identical to today's plain speech.
        self._revoicer = revoicer
        # Selects the canned() template variant (or the plain disabled literal)
        # for the LLM-free error/fallback lines below.
        self._persona_enabled = persona_enabled

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
        announce_gate = _BargeGate(self._barge_in_threshold, self._barge_in_trigger_frames)
        was_busy = False
        was_paused = False
        self._state_emitter.state("idle")
        log.info("Listening for wake word...")
        async for frame in frames:
            # Standing down: the user asked for silence, so wake detection is
            # suspended until the deadline passes or the TUI sends RESUME. Frames
            # keep draining (same rationale as the busy gate below).
            if self._standdown.active:
                preroll.clear()
                self._listen_event.clear()  # a tap while standing down is ignored
                if not was_paused:
                    # Pre-pause audio must not splice into a phantom wake on resume.
                    self._detector.reset()
                    self._state_emitter.state("paused", remaining=self._standdown.remaining)
                    log.info("Standing down; wake detection suspended")
                    was_paused = True
                continue
            if was_paused:  # RESUME verb or the stand-down timer expired
                was_paused = False
                self._state_emitter.state("idle")
                log.info("Stand-down ended; listening for wake word...")
            # A proactive announcement (a reminder) is playing: don't feed its
            # audio to the wake detector or it could self-trigger — unless
            # announcement barge-in is on, in which case frames keep scoring
            # behind the raised gate so the wake word can cut the announcement.
            if self._arbiter.busy:
                preroll.clear()
                if not was_busy:
                    # Drop the detector's rolling window on the way into busy, so
                    # audio from before the announcement can't splice with audio
                    # after it into a phantom wake once it ends.
                    self._detector.reset()
                    announce_gate.reset()
                    was_busy = True
                if self._barge_in_enabled and self._barge_in_announcements:
                    if announce_gate.offer(self._detector.process(frame)):
                        log.info("Barge-in: announcement cut, opening mic")
                        self._audio_out.stop()
                        # The holder's play() returns and it releases the arbiter;
                        # the next free frame consumes this as a manual turn.
                        self._listen_event.set()
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
                    open_cue=self._pick_wake_ack(event.score),
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
                        open_cue=self._pick_wake_ack(event.score),
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
        a new wake word, until the decision layer ends it, the user declines or
        says an end phrase, or silence closes it."""
        conv = Conversation(self._max_history_turns)
        reply_skill = None
        confirmed = False  # the check-in plays at most once per conversation
        while True:
            # A context-aware continuation decision (keep listening / confirm once /
            # end), made while the reply is spoken so it's ready by the time the
            # follow-up mic would open (no added mic latency).
            decision_task: asyncio.Task | None = None

            def start_decision(result, transcript=transcript):
                nonlocal decision_task
                if (
                    self._decision_enabled
                    and self._llm is not None
                    and self._conversation_enabled
                    and result.speech
                    and not result.expects_reply
                ):
                    turns = conv.history() + [
                        Turn("user", transcript),
                        Turn("assistant", result.speech),
                    ]
                    decision_task = asyncio.create_task(
                        self._decide_continuation(turns, confirmed)
                    )

            if reply_skill is not None:
                result = await self._dispatch_reply(
                    reply_skill, transcript, conv, on_reply=start_decision
                )
                reply_skill = None
                if result is not None and result.expects_reply:
                    log.warning("Reply result set expects_reply; ignored (one round only)")
            else:
                result, skill = await self._handle(
                    transcript, conv, spoken=True, on_reply=start_decision
                )
                if result is not None and result.expects_reply and skill is not None:
                    reply_skill = skill
            if self._standdown.active:
                # This turn engaged a stand-down; the confirmation is already
                # spoken. End the conversation now — no follow-up mic, no cue.
                self._drop_task(decision_task)
                return
            if self._barged:
                # The user spoke the wake word over the reply: playback is already
                # cut. Skip the continuation decision and reopen the mic right
                # away with no ack — the user is already talking.
                self._barged = False
                self._drop_task(decision_task)
                transcript = await self._capture_followup(frames)
                if not transcript:
                    if reply_skill is not None:
                        # Silence during a pending reply: deliver it as a cancel.
                        await self._dispatch_reply(reply_skill, "", conv)
                    return
                self._state_emitter.state("thinking", transcript=transcript)
                continue
            if reply_skill is None and not self._conversation_enabled:
                self._drop_task(decision_task)
                return
            if reply_skill is not None:
                # The skill just asked its own question: listen, no extra cue.
                self._drop_task(decision_task)
                action = "listen"
            else:
                action = await self._collect_decision(decision_task)
            if action == "confirm" and confirmed:
                # Already checked in once this conversation; a second completed
                # request ends it instead of chiming again.
                action = "end"
            if action == "end":
                return
            cue = None
            if action == "confirm":
                confirmed = True
                cue = self._confirm_earcon or None
            transcript = await self._capture_followup(frames, open_cue=cue)
            if not transcript:
                # Silence closes the conversation quietly — the descending tone at
                # mic-close already signalled the end.
                if reply_skill is not None:
                    # Silence during a pending reply: deliver it as a cancel.
                    await self._dispatch_reply(reply_skill, "", conv)
                return
            if reply_skill is None and self._is_end_phrase(transcript):
                # The user explicitly ended the conversation ("goodbye" / "I'm
                # done"): close it without routing the phrase to a skill.
                return
            if action == "confirm" and self._is_decline(transcript):
                # "No" right after the check-in ends the conversation; the
                # decline is never routed to a skill.
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

    def _pick_wake_ack(self, score: float) -> bytes | None:
        """A random pre-cached wake acknowledgement, or None if the pool is empty
        (e.g. tests). Scores below the confident threshold draw from the unsure
        pool ("Did you say something?"); confident wakes (and manual taps, which
        carry score 1.0) draw from the confident pool ("Hello!")."""
        pool = self._wake_earcons
        if score < self._wake_confident_threshold and self._unsure_wake_earcons:
            pool = self._unsure_wake_earcons
        return random.choice(pool) if pool else None

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
        if not pcm:
            return ""
        if self._min_transcribe_rms and rms < self._min_transcribe_rms:
            log.info(
                "Capture rms=%.0f below transcribe floor %.0f; treating as silence",
                rms,
                self._min_transcribe_rms,
            )
            return ""
        if self._normalize:
            pcm = normalize_peak(pcm, self._normalize_target_peak, self._normalize_rms_floor)
        transcript = await self._stt.transcribe(pcm)
        if (
            self._hallucination_max_rms
            and rms < self._hallucination_max_rms
            and self._is_hallucination(transcript)
        ):
            log.info("Dropping likely hallucination %r (rms=%.0f)", transcript, rms)
            return ""
        return transcript

    def _is_hallucination(self, transcript: str) -> bool:
        """True when the whole transcript is nothing but known hallucination
        phrases (matched as whole-token sequences, so repetitions like
        "Thank you. Thank you." qualify but "thank you for the reminder" doesn't)."""
        tokens = self._normalize_text(transcript).split()
        if not tokens:
            return False
        i = 0
        while i < len(tokens):
            for phrase in self._hallucination_phrases:
                if tokens[i : i + len(phrase)] == phrase:
                    i += len(phrase)
                    break
            else:
                return False
        return True

    async def _handle(self, transcript, conv, *, spoken, on_reply=None):
        try:
            result, skill = await self._orchestrator.handle(
                transcript, conv.history(), spoken=spoken, on_say=self._speak
            )
        except Exception as exc:  # noqa: BLE001 - a skill/LLM crash must not kill the loop
            log.error("Orchestration failed: %s", exc)
            self._state_emitter.state("error", message="Something went wrong.")
            await self._speak(
                canned("error_generic", enabled=self._persona_enabled), voiced=True
            )
            return None, None
        if result is None:
            log.warning("Nothing could handle %r", transcript)
            await self._speak(canned("cant_help", enabled=self._persona_enabled), voiced=True)
            return None, None
        log.info("Reply: %r", result.speech)
        if on_reply is not None:
            on_reply(result)  # kick off cue generation to overlap with playback
        await self._speak(result.speech, voiced=result.voiced)
        if result.restart:
            self._restart_in_place()
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
            await self._speak(
                canned("error_generic", enabled=self._persona_enabled), voiced=True
            )
            return None
        log.info("Reply: %r", result.speech)
        if on_reply is not None:
            on_reply(result)  # kick off cue generation to overlap with playback
        await self._speak(result.speech, voiced=result.voiced)
        if result.restart:
            self._restart_in_place()
        if transcript:
            conv.add("user", transcript)
        if result.speech:
            conv.add("assistant", result.speech)
        return result

    async def _decide_continuation(self, history: list[Turn], confirmed: bool) -> str:
        """Ask the LLM what to do after a reply: keep listening ("listen", the
        reply asked a question), check in once ("confirm" — the follow-up mic
        opens with a soft earcon), or close the conversation ("end"). Any
        failure degrades to "listen" — a silent reopen, the offline behavior."""
        prompt = self._render_history(history)
        if confirmed:
            prompt += "\n(You already checked in once this conversation.)"
        try:
            raw = await self._llm.complete(
                prompt, system=self._decision_prompt, json=True, label="decide"
            )
            action = json.loads(raw).get("action")
            if action not in ("listen", "confirm", "end"):
                raise ValueError(f"bad action {action!r}")
        except Exception as exc:  # noqa: BLE001 - decision failure degrades to a silent reopen
            log.warning("Continuation decision failed: %s", exc)
            return "listen"
        if action == "confirm" and confirmed:
            # Already checked in once this conversation: end instead of re-asking
            # (_converse enforces the same rule again).
            return "end"
        return action

    async def _collect_decision(self, task) -> str:
        """Await the pending decision up to its budget so it never delays
        mic-open; fall back to a silent listen if it isn't ready in time."""
        if task is None:
            return "listen"
        try:
            return await asyncio.wait_for(task, self._decision_timeout_s)
        except TimeoutError:
            log.info(
                "Continuation decision not ready in %.1fs; opening mic silently",
                self._decision_timeout_s,
            )
            task.cancel()
            return "listen"
        except Exception as exc:  # noqa: BLE001 - never block the loop on the decision
            log.warning("Continuation decision failed: %s", exc)
            return "listen"

    @staticmethod
    def _drop_task(task) -> None:
        if task is not None:
            task.cancel()

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

    def _is_decline(self, transcript: str) -> bool:
        # Exact match (unlike the end-phrase substring match): "no" must not
        # fire inside a longer follow-up like "no wait, one more thing".
        return self._normalize_text(transcript) in self._decline_phrases

    async def _speak(self, text: str, *, voiced: bool = False) -> bool:
        """Synthesize and play sentence by sentence so the first audio starts before
        the whole reply is synthesized, cutting the "wait for the full synth" stall.

        ``voiced`` marks text that is already persona-flavored (an LLM reply whose
        system prompt carried the persona suffix); it skips the Revoicer seam.
        Plain/deterministic text (``voiced=False``, the default) is restyled by the
        injected Revoicer first, when one is wired in.

        Returns True when the user barged in (wake word over playback): the rest
        of the reply is dropped and the caller reopens the mic."""
        if not voiced and self._revoicer is not None:
            text = await self._revoicer.revoice(text)
        self._barged = False
        self._state_emitter.state("speaking", text=text)
        barged = self._watch_for_barge_in()
        try:
            for sentence in _split_sentences(text):
                pcm = await self._tts.synthesize(sentence)
                if barged is None:
                    await self._play(pcm)
                elif barged.is_set() or await self._play_until_barge(pcm, barged):
                    log.info("Barge-in: reply cut, reopening mic")
                    self._barged = True
                    return True
        except Exception as exc:  # noqa: BLE001 - a synth/playback error must not kill the loop
            log.error("Speak failed: %s", exc)
        finally:
            if barged is not None:
                self._audio_in.clear_tap()
                self._detector.reset()
        return False

    def _watch_for_barge_in(self) -> asyncio.Event | None:
        """Install a mic tap that keeps scoring the wake word while we speak.

        The detector's own threshold/debounce still applies; on top, a barge
        needs ``barge_in_trigger_frames`` consecutive events at or above
        ``barge_in_threshold`` — an event below the raised bar resets the streak,
        so speaker echo that grazes the wake threshold can't cut the reply."""
        if not self._barge_in_enabled:
            return None
        barged = asyncio.Event()
        gate = _BargeGate(self._barge_in_threshold, self._barge_in_trigger_frames)

        def tap(frame: bytes) -> None:
            if gate.offer(self._detector.process(frame)):
                barged.set()

        self._detector.reset()  # this turn's own audio must not splice into a hit
        self._audio_in.set_tap(tap)
        return barged

    async def _play_until_barge(self, audio: bytes, barged: asyncio.Event) -> bool:
        """Play one clip, cutting it short when the barge watcher fires. Returns
        True when barged."""
        play_task = asyncio.create_task(self._play(audio))
        wait_task = asyncio.create_task(barged.wait())
        try:
            await asyncio.wait({play_task, wait_task}, return_when=asyncio.FIRST_COMPLETED)
        finally:
            if barged.is_set():
                self._audio_out.stop()  # unblocks the playback thread
            wait_task.cancel()
            await play_task  # never abandon playback mid-flight
        return barged.is_set()

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
