from collections import deque

from assistant.core.arbiter import AudioArbiter
from assistant.core.events import Command, Intent, SkillResult, Turn, WakeEvent
from assistant.core.pipeline import VoicePipeline
from assistant.skills.base import Skill

FRAME = bytes(2560)


class DirectOrchestrator:
    """Stand-in for the real Orchestrator: routes every turn to the one skill, so
    the pipeline tests exercise the wake/conversation loop, not tool routing (which
    has its own tests). Mirrors the (result, skill) contract the pipeline relies on."""

    def __init__(self, skill):
        self._skill = skill

    async def handle(self, text, history, *, spoken, on_say=None):
        result = await self._skill.handle(
            Command(text, spoken=spoken, history=history),
            Intent(type="general", raw_text=text),
        )
        return result, self._skill


class FakeAudioIn:
    def __init__(self, n):
        self._n = n
        self.drains = 0

    async def stream(self):
        for _ in range(self._n):
            yield FRAME

    def drain(self):
        self.drains += 1


class FakeDetector:
    def __init__(self, fires=1, score=0.9):
        self._remaining = fires
        self._score = score
        self.resets = 0

    @property
    def fired(self):
        return self._remaining <= 0

    def process(self, frame):
        if self._remaining > 0:
            self._remaining -= 1
            return WakeEvent("test", self._score)
        return None

    def reset(self):
        self.resets += 1


class FakeRecorder:
    def __init__(self, pcm=b"\x00\x00"):
        self.prefixes = []
        self.start_timeouts = []
        self._pcm = pcm

    async def record(self, frames, prefix=b"", start_timeout_ms=None, on_level=None,
                     cancel_event=None):
        self.prefixes.append(prefix)
        self.start_timeouts.append(start_timeout_ms)
        try:
            await frames.__anext__()  # consume one frame, like a real capture
        except StopAsyncIteration:
            pass
        return self._pcm


class FakeSTT:
    """Constant transcript, or a scripted list where "" marks silence and the
    queue yields "" once exhausted."""

    def __init__(self, transcript="what time is it", transcripts=None):
        self.calls = []
        self._transcript = transcript
        self._queue = deque(transcripts) if transcripts is not None else None

    async def transcribe(self, audio):
        self.calls.append(audio)
        if self._queue is not None:
            return self._queue.popleft() if self._queue else ""
        return self._transcript


class RaisingSkill(Skill):
    name = "raising"
    intents = {"general"}

    async def handle(self, cmd, intent):
        raise RuntimeError("skill boom")


class FakeSkill(Skill):
    name = "fake"
    intents = {"general"}

    def __init__(self, speech="it is noon", expects_reply=False,
                 reply_speech="reply handled", reply_restart=False):
        self.handled = []
        self.histories = []
        self.spokens = []
        self.replies = []
        self._speech = speech
        self._expects_reply = expects_reply
        self._reply_speech = reply_speech
        self._reply_restart = reply_restart

    async def handle(self, cmd, intent):
        self.handled.append((cmd.text, intent.type))
        self.histories.append(cmd.history)
        self.spokens.append(cmd.spoken)
        return SkillResult(speech=self._speech, expects_reply=self._expects_reply)

    async def handle_reply(self, cmd):
        self.replies.append(cmd.text)
        return SkillResult(speech=self._reply_speech, restart=self._reply_restart)


class FakeTTS:
    def __init__(self):
        self.spoke = []

    async def synthesize(self, text):
        self.spoke.append(text)
        return b"AUDIO"


class FakeOut:
    def __init__(self):
        self.played = []
        self.stops = 0

    async def play(self, audio):
        self.played.append(audio)

    def stop(self):
        self.stops += 1


class FakeLLM:
    """Records completions and returns a fixed text (or raises), so the decision
    path can be exercised without a real model. Each call logs
    (prompt, system, label); `jsons` logs (label, json) for format assertions."""

    def __init__(self, text="take care", raises=False):
        self.calls = []
        self.jsons = []
        self._text = text
        self._raises = raises

    async def complete(self, prompt, *, system=None, json=False, label=""):
        self.calls.append((prompt, system, label))
        self.jsons.append((label, json))
        if self._raises:
            raise RuntimeError("llm down")
        return self._text


def _pipeline(audio_in, detector, skill, tts, out, arbiter, *, stt=None,
              recorder=None, no_speech_earcon=b"", wake_earcon=b"", wake_earcons=None,
              unsure_wake_earcons=None, wake_confident_threshold=0.0,
              end_earcon=b"", conversation_enabled=False, followup_window_ms=6000,
              max_history_turns=12, min_transcribe_rms=0.0,
              hallucination_phrases=None, hallucination_max_rms=0.0,
              state_emitter=None, llm=None, decision_enabled=False,
              decision_prompt="decide", decision_timeout_s=4.0,
              decline_phrases=None, confirm_earcon=b"", end_phrases=None,
              ack_delay_s=0.0, standdown=None, barge_in_enabled=False,
              barge_in_threshold=0.8, barge_in_trigger_frames=3,
              barge_in_announcements=False, restart_in_place=None):
    # Tests pass a single wake_earcon for convenience; the pipeline takes a pool.
    if wake_earcons is None:
        wake_earcons = [wake_earcon] if wake_earcon else []
    return VoicePipeline(
        audio_in, detector, recorder or FakeRecorder(), stt or FakeSTT(),
        DirectOrchestrator(skill), tts, out, arbiter,
        no_speech_earcon=no_speech_earcon,
        wake_earcons=wake_earcons,
        unsure_wake_earcons=unsure_wake_earcons,
        wake_confident_threshold=wake_confident_threshold,
        end_earcon=end_earcon,
        min_transcribe_rms=min_transcribe_rms,
        hallucination_phrases=hallucination_phrases,
        hallucination_max_rms=hallucination_max_rms,
        conversation_enabled=conversation_enabled,
        followup_window_ms=followup_window_ms,
        max_history_turns=max_history_turns,
        llm=llm,
        decision_enabled=decision_enabled,
        decision_timeout_s=decision_timeout_s,
        decision_prompt=decision_prompt,
        decline_phrases=decline_phrases,
        confirm_earcon=confirm_earcon,
        end_phrases=end_phrases,
        ack_delay_s=ack_delay_s,
        state_emitter=state_emitter,
        standdown=standdown,
        barge_in_enabled=barge_in_enabled,
        barge_in_threshold=barge_in_threshold,
        barge_in_trigger_frames=barge_in_trigger_frames,
        barge_in_announcements=barge_in_announcements,
        restart_in_place=restart_in_place,
    )


async def test_wake_routes_and_speaks_reply():
    detector = FakeDetector()
    skill = FakeSkill()
    tts = FakeTTS()
    out = FakeOut()
    pipeline = _pipeline(FakeAudioIn(3), detector, skill, tts, out, AudioArbiter())

    await pipeline.run()

    assert skill.handled == [("what time is it", "general")]  # routed to skill
    assert tts.spoke == ["it is noon"]                        # spoke the reply
    assert out.played == [b"AUDIO"]                           # played the audio
    assert detector.resets == 1                               # reset after handling


async def test_speak_chunks_multi_sentence_reply():
    # A multi-sentence reply is synthesized and played sentence by sentence, so the
    # first audio starts before the whole reply is synthesized.
    skill = FakeSkill(speech="It is noon. The sun is out.")
    tts = FakeTTS()
    out = FakeOut()
    pipeline = _pipeline(FakeAudioIn(3), FakeDetector(), skill, tts, out, AudioArbiter())

    await pipeline.run()

    assert tts.spoke == ["It is noon.", "The sun is out."]
    assert out.played == [b"AUDIO", b"AUDIO"]


async def test_speak_single_sentence_plays_once():
    skill = FakeSkill(speech="It is noon.")
    tts = FakeTTS()
    out = FakeOut()
    pipeline = _pipeline(FakeAudioIn(3), FakeDetector(), skill, tts, out, AudioArbiter())

    await pipeline.run()

    assert tts.spoke == ["It is noon."]
    assert out.played == [b"AUDIO"]


class BusyThenFreeIn:
    """Yields one frame while the arbiter is busy, then frees it and yields more.

    Exercises the busy->free edge: the pipeline must drop the detector's window on
    the way into busy so pre-announcement audio can't splice into a phantom wake.
    """

    def __init__(self, arbiter, tail=2):
        self._arbiter = arbiter
        self._tail = tail

    async def stream(self):
        await self._arbiter._lock.acquire()  # busy
        yield FRAME  # pipeline sees busy -> should reset the detector once
        self._arbiter._lock.release()  # free again
        for _ in range(self._tail):
            yield FRAME

    def drain(self):
        pass


async def test_detector_reset_on_busy_edge():
    detector = FakeDetector()
    skill = FakeSkill()
    arbiter = AudioArbiter()
    pipeline = _pipeline(BusyThenFreeIn(arbiter), detector, skill, FakeTTS(), FakeOut(), arbiter)

    await pipeline.run()

    # One reset on the busy edge + one after the turn completes.
    assert detector.resets == 2
    assert skill.handled == [("what time is it", "general")]  # woke normally after busy


class RecordingEmitter:
    def __init__(self):
        self.states = []
        self.fields = []
        self.levels = []

    def state(self, name, **fields):
        self.states.append(name)
        self.fields.append(fields)

    def level(self, rms):
        self.levels.append(rms)


async def test_state_feed_emits_turn_sequence():
    # A normal turn walks idle -> listening -> thinking -> speaking -> idle so the
    # TUI can mirror whose turn it is. The transcript rides the post-STT thinking.
    emitter = RecordingEmitter()
    skill = FakeSkill()
    pipeline = _pipeline(
        FakeAudioIn(3), FakeDetector(), skill, FakeTTS(), FakeOut(), AudioArbiter(),
        state_emitter=emitter,
    )

    await pipeline.run()

    assert emitter.states == [
        "idle", "listening", "thinking", "thinking", "speaking", "idle",
    ]
    # The second thinking carries what was heard, for the "you said: ..." line.
    assert emitter.fields[3] == {"transcript": "what time is it"}


async def test_state_feed_reports_no_speech():
    emitter = RecordingEmitter()
    pipeline = _pipeline(
        FakeAudioIn(3), FakeDetector(), FakeSkill(), FakeTTS(), FakeOut(), AudioArbiter(),
        stt=FakeSTT(transcript=""), state_emitter=emitter,
    )

    await pipeline.run()

    # The empty initial capture triggers one mic reopen (a second listening/
    # thinking pair) before giving up on no_speech.
    assert emitter.states == [
        "idle", "listening", "thinking", "listening", "thinking", "no_speech", "idle",
    ]


async def test_manual_listen_starts_turn_without_wake():
    # tap-to-listen: request_listen() makes the loop enter a turn even though the
    # detector never fires — the escape hatch when the wake word is missed.
    detector = FakeDetector(fires=0)  # never wakes on its own
    skill = FakeSkill()
    pipeline = _pipeline(FakeAudioIn(3), detector, skill, FakeTTS(), FakeOut(), AudioArbiter())
    pipeline.request_listen()

    await pipeline.run()

    assert skill.handled == [("what time is it", "general")]  # ran without a wake word


async def test_cancel_stops_playback():
    # tap-to-cancel / barge-in: cancel() aborts any playback immediately.
    out = FakeOut()
    pipeline = _pipeline(FakeAudioIn(0), FakeDetector(), FakeSkill(), FakeTTS(), out, AudioArbiter())

    pipeline.cancel()

    assert out.stops == 1


async def test_low_rms_capture_skips_stt():
    # A near-silent capture (FakeRecorder returns zeroed PCM) must not reach
    # whisper, which hallucinates text on silence; it takes the no-speech path.
    skill = FakeSkill()
    stt = FakeSTT(transcript="phantom words")
    out = FakeOut()
    pipeline = _pipeline(
        FakeAudioIn(3), FakeDetector(), skill, FakeTTS(), out, AudioArbiter(),
        stt=stt, no_speech_earcon=b"BEEP", min_transcribe_rms=50.0,
    )

    await pipeline.run()

    assert stt.calls == []          # whisper never called on the silent capture
    assert skill.handled == []      # nothing routed
    assert out.played == [b"BEEP"]  # no-speech earcon instead


async def test_busy_arbiter_skips_wake_detection():
    # While another holder (a proactive reminder) owns the audio, the loop must
    # not run wake detection on the announcement audio bleeding into the mic.
    detector = FakeDetector()
    skill = FakeSkill()
    tts = FakeTTS()
    out = FakeOut()
    arbiter = AudioArbiter()
    pipeline = _pipeline(FakeAudioIn(3), detector, skill, tts, out, arbiter)

    async with arbiter.hold("reminder"):
        await pipeline.run()

    assert detector.fired is False  # never processed a frame
    assert skill.handled == []
    assert tts.spoke == []
    assert out.played == []


async def test_wake_plays_ding_before_reply():
    # The ding plays the instant the wake word fires, before the captured reply.
    skill = FakeSkill()
    tts = FakeTTS()
    out = FakeOut()
    pipeline = _pipeline(
        FakeAudioIn(3), FakeDetector(), skill, tts, out, AudioArbiter(),
        wake_earcon=b"DING",
    )

    await pipeline.run()

    assert out.played == [b"DING", b"AUDIO"]  # ding first, then the spoken reply


async def test_wake_cue_picked_from_pool():
    # With a pool of acknowledgements, the wake cue is one of them (chosen at random).
    pool = [b"ACK1", b"ACK2", b"ACK3"]
    skill = FakeSkill()
    out = FakeOut()
    pipeline = _pipeline(
        FakeAudioIn(3), FakeDetector(), skill, FakeTTS(), out, AudioArbiter(),
        wake_earcons=pool,
    )

    await pipeline.run()

    assert out.played[0] in pool          # the mic-open cue is from the pool
    assert out.played[-1] == b"AUDIO"     # reply still spoken


async def test_confident_wake_uses_confident_ack_pool():
    # A score at/above the confident threshold greets enthusiastically.
    out = FakeOut()
    pipeline = _pipeline(
        FakeAudioIn(3), FakeDetector(score=0.9), FakeSkill(), FakeTTS(), out,
        AudioArbiter(),
        wake_earcons=[b"HELLO"], unsure_wake_earcons=[b"WHAT"],
        wake_confident_threshold=0.85,
    )

    await pipeline.run()

    assert out.played[0] == b"HELLO"


async def test_low_confidence_wake_uses_unsure_ack_pool():
    # A score between the fire threshold and the confident threshold signals an
    # uncertain pickup ("did you say something?").
    out = FakeOut()
    pipeline = _pipeline(
        FakeAudioIn(3), FakeDetector(score=0.7), FakeSkill(), FakeTTS(), out,
        AudioArbiter(),
        wake_earcons=[b"HELLO"], unsure_wake_earcons=[b"WHAT"],
        wake_confident_threshold=0.85,
    )

    await pipeline.run()

    assert out.played[0] == b"WHAT"


async def test_manual_listen_uses_confident_ack_pool():
    # A tap-to-listen carries score 1.0 and never sounds unsure.
    out = FakeOut()
    pipeline = _pipeline(
        FakeAudioIn(3), FakeDetector(fires=0), FakeSkill(), FakeTTS(), out,
        AudioArbiter(),
        wake_earcons=[b"HELLO"], unsure_wake_earcons=[b"WHAT"],
        wake_confident_threshold=0.85,
    )
    pipeline.request_listen()

    await pipeline.run()

    assert out.played[0] == b"HELLO"


async def test_low_confidence_wake_falls_back_without_unsure_pool():
    # No unsure pool configured -> every wake draws from the confident pool.
    out = FakeOut()
    pipeline = _pipeline(
        FakeAudioIn(3), FakeDetector(score=0.7), FakeSkill(), FakeTTS(), out,
        AudioArbiter(),
        wake_earcons=[b"HELLO"], wake_confident_threshold=0.85,
    )

    await pipeline.run()

    assert out.played[0] == b"HELLO"


async def test_end_earcon_plays_at_mic_close():
    # The mic-open cue plays on wake, the mic-close cue the instant recording ends
    # (before the reply), so the listening window is audibly bracketed.
    skill = FakeSkill()
    out = FakeOut()
    pipeline = _pipeline(
        FakeAudioIn(3), FakeDetector(), skill, FakeTTS(), out, AudioArbiter(),
        wake_earcon=b"ACK", end_earcon=b"END",
    )

    await pipeline.run()

    assert out.played == [b"ACK", b"END", b"AUDIO"]  # open, close, then the reply


async def test_input_drained_after_wake_cue():
    # After playing the spoken ack, buffered mic frames (its echo) are dropped
    # before recording so the ack isn't transcribed into the command.
    audio_in = FakeAudioIn(3)
    pipeline = _pipeline(
        audio_in, FakeDetector(), FakeSkill(), FakeTTS(), FakeOut(), AudioArbiter(),
        wake_earcon=b"ACK",
    )

    await pipeline.run()

    assert audio_in.drains == 1  # drained once, after the ack, before recording


async def test_wake_without_earcon_plays_no_ding():
    skill = FakeSkill()
    tts = FakeTTS()
    out = FakeOut()
    pipeline = _pipeline(
        FakeAudioIn(3), FakeDetector(), skill, tts, out, AudioArbiter(),
    )  # default wake_earcon is empty

    await pipeline.run()

    assert out.played == [b"AUDIO"]  # only the reply, no ding


async def test_no_speech_plays_earcon():
    skill = FakeSkill()
    tts = FakeTTS()
    out = FakeOut()
    pipeline = _pipeline(
        FakeAudioIn(3), FakeDetector(), skill, tts, out, AudioArbiter(),
        stt=FakeSTT(transcript=""), no_speech_earcon=b"BEEP",
    )

    await pipeline.run()

    assert out.played == [b"BEEP"]  # blip instead of silence
    assert skill.handled == []      # nothing transcribed -> no routing
    assert tts.spoke == []


async def test_no_speech_without_earcon_plays_nothing():
    skill = FakeSkill()
    tts = FakeTTS()
    out = FakeOut()
    pipeline = _pipeline(
        FakeAudioIn(3), FakeDetector(), skill, tts, out, AudioArbiter(),
        stt=FakeSTT(transcript=""),  # default earcon is empty
    )

    await pipeline.run()

    assert out.played == []
    assert tts.spoke == []


async def test_submit_text_routes_like_a_spoken_turn():
    # A typed command (TUI chat box) runs the same route -> skill -> speak path.
    skill = FakeSkill()
    tts = FakeTTS()
    out = FakeOut()
    pipeline = _pipeline(FakeAudioIn(0), FakeDetector(), skill, tts, out, AudioArbiter())

    await pipeline.submit_text("  what time is it  ")

    assert skill.handled == [("what time is it", "general")]  # stripped + routed
    assert tts.spoke == ["it is noon"]
    assert out.played == [b"AUDIO"]


async def test_submit_text_holds_arbiter():
    # The typed turn must acquire the audio arbiter so it can't collide with a
    # reminder announcement or wake capture.
    skill = FakeSkill()
    arbiter = AudioArbiter()
    pipeline = _pipeline(FakeAudioIn(0), FakeDetector(), skill, FakeTTS(), FakeOut(), arbiter)

    async with arbiter.hold("reminder"):
        # Arbiter is held: submit_text should block, so run it with a timeout and
        # confirm nothing was handled while we held the lock.
        import asyncio

        with __import__("pytest").raises(asyncio.TimeoutError):
            await asyncio.wait_for(pipeline.submit_text("hello"), timeout=0.05)
    assert skill.handled == []  # never routed while the arbiter was held


async def test_submit_text_ignores_blank():
    skill = FakeSkill()
    pipeline = _pipeline(FakeAudioIn(0), FakeDetector(), skill, FakeTTS(), FakeOut(), AudioArbiter())
    await pipeline.submit_text("   ")
    assert skill.handled == []


class BoomOut:
    """An output device whose playback fails (e.g. unplugged mid-turn)."""

    async def play(self, audio):
        raise RuntimeError("audio device gone")


async def test_playback_failure_does_not_kill_the_loop():
    # A play() error must not escape _handle -> the wake loop; otherwise the
    # daemon stops listening and goes deaf until restarted.
    detector = FakeDetector()
    skill = FakeSkill()
    pipeline = _pipeline(FakeAudioIn(3), detector, skill, FakeTTS(), BoomOut(), AudioArbiter())

    await pipeline.run()  # completes instead of raising

    assert skill.handled == [("what time is it", "general")]
    assert detector.resets == 1  # turn completed; loop kept going


async def test_skill_exception_is_spoken_and_loop_survives():
    detector = FakeDetector()
    tts = FakeTTS()
    out = FakeOut()
    pipeline = _pipeline(FakeAudioIn(3), detector, RaisingSkill(), tts, out, AudioArbiter())

    await pipeline.run()

    assert tts.spoke == ["Sorry, something went wrong."]
    assert out.played == [b"AUDIO"]
    assert detector.resets == 1  # turn completed; loop kept going


async def test_empty_initial_capture_retries_once_then_routes():
    # A beat-too-slow first attempt reopens the mic once; the retry's transcript
    # runs the normal turn, and the recorder is called exactly twice.
    detector = FakeDetector()
    skill = FakeSkill()
    recorder = FakeRecorder()
    stt = FakeSTT(transcripts=["", "what time is it"])
    pipeline = _pipeline(
        FakeAudioIn(3), detector, skill, FakeTTS(), FakeOut(), AudioArbiter(),
        stt=stt, recorder=recorder,
    )

    await pipeline.run()

    assert skill.handled == [("what time is it", "general")]  # retry routed
    assert len(recorder.start_timeouts) == 2                  # initial + one retry
    assert recorder.start_timeouts == [None, 6000]            # retry uses the window


async def test_empty_initial_capture_retries_only_once():
    # Both attempts silent: exactly one retry (recorder called twice), then the
    # no-speech path — no third attempt, no routing.
    detector = FakeDetector()
    skill = FakeSkill()
    recorder = FakeRecorder()
    emitter = RecordingEmitter()
    stt = FakeSTT(transcripts=["", ""])
    pipeline = _pipeline(
        FakeAudioIn(3), detector, skill, FakeTTS(), FakeOut(), AudioArbiter(),
        stt=stt, recorder=recorder, no_speech_earcon=b"BEEP", state_emitter=emitter,
    )

    await pipeline.run()

    assert skill.handled == []                       # nothing routed
    assert len(recorder.start_timeouts) == 2         # initial + one retry, no third
    assert "no_speech" in emitter.states


async def test_orchestration_failure_emits_error_state():
    emitter = RecordingEmitter()
    pipeline = _pipeline(
        FakeAudioIn(3), FakeDetector(), RaisingSkill(), FakeTTS(), FakeOut(), AudioArbiter(),
        state_emitter=emitter,
    )

    await pipeline.run()

    assert "error" in emitter.states
    assert "message" in emitter.fields[emitter.states.index("error")]


class ReplyLoopSkill(FakeSkill):
    """A skill whose reply itself asks for another reply (to test one-round-only)."""

    async def handle_reply(self, cmd):
        self.replies.append(cmd.text)
        return SkillResult(speech="still there?", expects_reply=True)


async def test_followup_captured_without_wake():
    # After the first answer, a follow-up is recorded and handled without a new
    # wake word, using the follow-up window as the record start timeout.
    detector = FakeDetector(fires=1)
    skill = FakeSkill()
    recorder = FakeRecorder()
    stt = FakeSTT(transcripts=["what time is it", "and the date"])
    pipeline = _pipeline(
        FakeAudioIn(6), detector, skill, FakeTTS(), FakeOut(), AudioArbiter(),
        stt=stt, recorder=recorder, conversation_enabled=True, followup_window_ms=6000,
    )

    await pipeline.run()

    assert [t for (t, _) in skill.handled] == ["what time is it", "and the date"]
    assert detector.resets == 1                     # one wake, one conversation
    assert recorder.start_timeouts[0] is None       # initial capture: no override
    assert recorder.start_timeouts[1:] == [6000, 6000]  # follow-ups use the window


async def test_silence_ends_conversation_and_new_wake_is_fresh():
    detector = FakeDetector(fires=2)
    skill = FakeSkill()
    stt = FakeSTT(transcripts=["first question", "", "second question", ""])
    pipeline = _pipeline(
        FakeAudioIn(10), detector, skill, FakeTTS(), FakeOut(), AudioArbiter(),
        stt=stt, conversation_enabled=True,
    )

    await pipeline.run()

    assert [t for (t, _) in skill.handled] == ["first question", "second question"]
    assert detector.resets == 2      # two separate conversations
    assert skill.histories[0] == []  # first conversation starts empty
    assert skill.histories[1] == []  # second wake does not carry turn 1


async def test_second_turn_carries_history():
    skill = FakeSkill(speech="it is noon")
    stt = FakeSTT(transcripts=["what time is it", "and tomorrow", ""])
    pipeline = _pipeline(
        FakeAudioIn(8), FakeDetector(), skill, FakeTTS(), FakeOut(), AudioArbiter(),
        stt=stt, conversation_enabled=True,
    )

    await pipeline.run()

    assert skill.histories[0] == []
    assert skill.histories[1] == [
        Turn("user", "what time is it"),
        Turn("assistant", "it is noon"),
    ]


async def test_history_cap_respected():
    skill = FakeSkill(speech="ok")
    stt = FakeSTT(transcripts=["one", "two", "three", ""])
    pipeline = _pipeline(
        FakeAudioIn(10), FakeDetector(), skill, FakeTTS(), FakeOut(), AudioArbiter(),
        stt=stt, conversation_enabled=True, max_history_turns=2,
    )

    await pipeline.run()

    # Turn 3 sees only the last two messages: turn 2's user + assistant.
    assert skill.histories[2] == [Turn("user", "two"), Turn("assistant", "ok")]


async def test_expects_reply_routes_followup_to_handle_reply():
    skill = FakeSkill(speech="confirm?", expects_reply=True)
    stt = FakeSTT(transcripts=["turn off for 20 minutes", "confirm"])
    tts = FakeTTS()
    pipeline = _pipeline(
        FakeAudioIn(6), FakeDetector(), skill, tts, FakeOut(), AudioArbiter(),
        stt=stt, conversation_enabled=False,  # reply round runs even when disabled
    )

    await pipeline.run()

    assert [t for (t, _) in skill.handled] == ["turn off for 20 minutes"]  # routed once
    assert skill.replies == ["confirm"]                # follow-up went to handle_reply
    assert tts.spoke == ["confirm?", "reply handled"]  # prompt then reply outcome


async def test_reply_is_one_round_only():
    skill = ReplyLoopSkill(speech="confirm?", expects_reply=True)
    stt = FakeSTT(transcripts=["turn off for 20 minutes", "confirm", "again"])
    pipeline = _pipeline(
        FakeAudioIn(8), FakeDetector(), skill, FakeTTS(), FakeOut(), AudioArbiter(),
        stt=stt, conversation_enabled=False,
    )

    await pipeline.run()

    assert skill.replies == ["confirm"]  # the reply's expects_reply is ignored


async def test_pipeline_invokes_restart_after_speaking():
    # The restart must happen only after the sign-off has been spoken (played),
    # never before — otherwise the process is replaced mid-sentence.
    order = []

    class OrderedOut(FakeOut):
        async def play(self, audio):
            await super().play(audio)
            order.append("play")

    def restart_fn():
        order.append("restart")

    skill = FakeSkill(speech="confirm?", expects_reply=True,
                       reply_speech="signing off", reply_restart=True)
    stt = FakeSTT(transcripts=["update please", "yes"])
    pipeline = _pipeline(
        FakeAudioIn(6), FakeDetector(), skill, FakeTTS(), OrderedOut(), AudioArbiter(),
        stt=stt, conversation_enabled=False, restart_in_place=restart_fn,
    )

    await pipeline.run()

    assert skill.replies == ["yes"]
    assert order == ["play", "play", "restart"]  # confirm prompt, sign-off, then restart


async def test_decline_or_silence_cancels_no_restart():
    # A negative/unrelated/silent reply (SkillResult.restart stays False, the
    # default) must never trigger the injected restart callable.
    calls = []
    skill = FakeSkill(speech="confirm?", expects_reply=True,
                       reply_speech="okay, never mind", reply_restart=False)
    stt = FakeSTT(transcripts=["update please", ""])
    pipeline = _pipeline(
        FakeAudioIn(6), FakeDetector(), skill, FakeTTS(), FakeOut(), AudioArbiter(),
        stt=stt, conversation_enabled=True, restart_in_place=calls.append,
    )

    await pipeline.run()

    assert skill.replies == [""]
    assert calls == []


async def test_silence_during_pending_reply_cancels():
    skill = FakeSkill(speech="confirm?", expects_reply=True)
    stt = FakeSTT(transcripts=["turn off for 20 minutes", ""])
    pipeline = _pipeline(
        FakeAudioIn(6), FakeDetector(), skill, FakeTTS(), FakeOut(), AudioArbiter(),
        stt=stt, conversation_enabled=True,
    )

    await pipeline.run()

    assert skill.replies == [""]  # silence delivered to the pending skill as cancel


async def test_submit_text_carries_history_and_never_replies():
    skill = FakeSkill(speech="Frank Herbert.", expects_reply=True)
    pipeline = _pipeline(
        FakeAudioIn(0), FakeDetector(), skill, FakeTTS(), FakeOut(), AudioArbiter(),
        conversation_enabled=True,
    )

    await pipeline.submit_text("who wrote Dune")
    await pipeline.submit_text("when did he die")

    assert skill.histories[0] == []
    assert skill.histories[1] == [
        Turn("user", "who wrote Dune"),
        Turn("assistant", "Frank Herbert."),
    ]
    assert skill.spokens == [False, False]  # typed path is not spoken
    assert skill.replies == []              # typed expects_reply opens no reply round


async def test_racing_tap_cleared_by_real_wake():
    # A tap-to-listen flag set while a real wake fires must be consumed by that
    # wake, not leak into a spurious extra turn on a later silent frame.
    detector = FakeDetector(fires=1)  # wakes on the first frame
    skill = FakeSkill()
    pipeline = _pipeline(FakeAudioIn(3), detector, skill, FakeTTS(), FakeOut(), AudioArbiter())
    pipeline.request_listen()  # racing tap set before the wake

    await pipeline.run()

    assert skill.handled == [("what time is it", "general")]  # exactly one turn
    assert not pipeline._listen_event.is_set()                # tap consumed by the wake


async def test_followup_thinking_carries_transcript():
    # Each follow-up re-emits thinking with its transcript, so the TUI's "you said"
    # line fills for follow-ups, not just the first turn.
    emitter = RecordingEmitter()
    skill = FakeSkill()
    stt = FakeSTT(transcripts=["what time is it", "and the date", ""])
    pipeline = _pipeline(
        FakeAudioIn(8), FakeDetector(), skill, FakeTTS(), FakeOut(), AudioArbiter(),
        stt=stt, conversation_enabled=True, state_emitter=emitter,
    )

    await pipeline.run()

    thinking_transcripts = [
        f.get("transcript")
        for s, f in zip(emitter.states, emitter.fields)
        if s == "thinking" and "transcript" in f
    ]
    assert thinking_transcripts == ["what time is it", "and the date"]


async def test_conversation_disabled_records_once_per_wake():
    recorder = FakeRecorder()
    skill = FakeSkill()
    pipeline = _pipeline(
        FakeAudioIn(3), FakeDetector(), skill, FakeTTS(), FakeOut(), AudioArbiter(),
        recorder=recorder, conversation_enabled=False,
    )

    await pipeline.run()

    assert recorder.start_timeouts == [None]  # only the initial capture, no follow-up


async def test_followup_does_not_replay_wake_ack():
    # The wake ack ("hmm?") plays only on the first wake. A follow-up mic-open no
    # longer replays it (which read as acknowledging nothing after an answer).
    skill = FakeSkill()
    stt = FakeSTT(transcripts=["what time is it", "and the date", ""])
    out = FakeOut()
    pipeline = _pipeline(
        FakeAudioIn(8), FakeDetector(), skill, FakeTTS(), out, AudioArbiter(),
        stt=stt, conversation_enabled=True, wake_earcon=b"ACK",
    )  # decision disabled -> the follow-up mic opens silently

    await pipeline.run()

    assert [t for (t, _) in skill.handled] == ["what time is it", "and the date"]
    assert out.played.count(b"ACK") == 1  # only the first wake, never the follow-ups


async def test_confirm_plays_checkin_earcon():
    # A "confirm" decision opens the follow-up mic with the check-in earcon —
    # no phrase is ever synthesized for it.
    skill = FakeSkill(speech="it is noon")
    stt = FakeSTT(transcripts=["what time is it", ""])
    tts = FakeTTS()
    out = FakeOut()
    llm = FakeLLM('{"action": "confirm"}')
    pipeline = _pipeline(
        FakeAudioIn(6), FakeDetector(), skill, tts, out, AudioArbiter(),
        stt=stt, conversation_enabled=True, llm=llm, decision_enabled=True,
        confirm_earcon=b"CHECK",
    )

    await pipeline.run()

    assert b"CHECK" in out.played          # earcon marks the check-in at mic-open
    assert tts.spoke == ["it is noon"]     # only the reply; no check-in phrase
    assert ("decide", True) in llm.jsons   # decision requested as structured JSON


async def test_decision_degrades_on_llm_failure():
    # A decision LLM that raises must not break the loop: the follow-up mic just
    # opens silently and the conversation continues (ends on silence, as before).
    skill = FakeSkill()
    stt = FakeSTT(transcripts=["what time is it", "and the date", ""])
    out = FakeOut()
    llm = FakeLLM(raises=True)
    pipeline = _pipeline(
        FakeAudioIn(8), FakeDetector(), skill, FakeTTS(), out, AudioArbiter(),
        stt=stt, conversation_enabled=True, llm=llm,
        decision_enabled=True, wake_earcon=b"ACK",
    )

    await pipeline.run()

    assert [t for (t, _) in skill.handled] == ["what time is it", "and the date"]
    assert out.played.count(b"ACK") == 1  # still no ack replayed on the follow-up


async def test_listen_decision_reopens_mic_silently():
    # A "listen" decision (the reply asked a question) reopens the mic with no
    # extra cue: only the replies themselves are synthesized.
    skill = FakeSkill(speech="which city?")
    stt = FakeSTT(transcripts=["weather", "paris", ""])
    tts = FakeTTS()
    recorder = FakeRecorder()
    llm = FakeLLM('{"action": "listen"}')
    pipeline = _pipeline(
        FakeAudioIn(8), FakeDetector(), skill, tts, FakeOut(), AudioArbiter(),
        stt=stt, recorder=recorder, conversation_enabled=True, llm=llm,
        decision_enabled=True,
    )

    await pipeline.run()

    assert [t for (t, _) in skill.handled] == ["weather", "paris"]
    assert tts.spoke == ["which city?", "which city?"]  # replies only, no cue
    assert recorder.start_timeouts[1:] == [6000, 6000]  # mic reopened both times


async def test_end_decision_closes_without_reopen():
    # An "end" decision closes the conversation right after the reply: the
    # follow-up mic never opens.
    skill = FakeSkill(speech="done, timer set")
    recorder = FakeRecorder()
    stt = FakeSTT(transcripts=["set a timer"])
    llm = FakeLLM('{"action": "end"}')
    pipeline = _pipeline(
        FakeAudioIn(6), FakeDetector(), skill, FakeTTS(), FakeOut(), AudioArbiter(),
        stt=stt, recorder=recorder, conversation_enabled=True, llm=llm,
        decision_enabled=True,
    )

    await pipeline.run()

    assert [t for (t, _) in skill.handled] == ["set a timer"]
    assert recorder.start_timeouts == [None]  # initial capture only, no follow-up


async def test_confirm_second_time_ends_instead():
    # The check-in plays at most once per conversation: a second "confirm"
    # decision degrades to "end" instead of chiming again.
    skill = FakeSkill(speech="done")
    recorder = FakeRecorder()
    stt = FakeSTT(transcripts=["set a timer", "what's the weather", "more", ""])
    out = FakeOut()
    llm = FakeLLM('{"action": "confirm"}')
    pipeline = _pipeline(
        FakeAudioIn(10), FakeDetector(), skill, FakeTTS(), out, AudioArbiter(),
        stt=stt, recorder=recorder, conversation_enabled=True, llm=llm,
        decision_enabled=True, confirm_earcon=b"CHECK",
    )

    await pipeline.run()

    assert [t for (t, _) in skill.handled] == ["set a timer", "what's the weather"]
    assert out.played.count(b"CHECK") == 1  # chimed once, never repeated
    assert recorder.start_timeouts == [None, 6000]  # second completed turn ended


async def test_decline_after_confirm_ends_and_is_not_routed():
    # "No" right after the check-in chime ends the conversation and is never
    # routed to a skill.
    skill = FakeSkill(speech="done")
    stt = FakeSTT(transcripts=["set a timer", "no"])
    llm = FakeLLM('{"action": "confirm"}')
    pipeline = _pipeline(
        FakeAudioIn(8), FakeDetector(), skill, FakeTTS(), FakeOut(), AudioArbiter(),
        stt=stt, conversation_enabled=True, llm=llm,
        decision_enabled=True, decline_phrases=["no", "nope"],
    )

    await pipeline.run()

    assert [t for (t, _) in skill.handled] == ["set a timer"]  # "no" never routed


async def test_bad_decision_json_falls_back_to_listen():
    # Malformed decision output degrades to a silent listen; the loop continues
    # and still ends on silence.
    skill = FakeSkill()
    stt = FakeSTT(transcripts=["one", "two", ""])
    llm = FakeLLM("not json at all")
    pipeline = _pipeline(
        FakeAudioIn(8), FakeDetector(), skill, FakeTTS(), FakeOut(), AudioArbiter(),
        stt=stt, conversation_enabled=True, llm=llm, decision_enabled=True,
    )

    await pipeline.run()

    assert [t for (t, _) in skill.handled] == ["one", "two"]


async def test_expects_reply_skips_decision():
    # A reply-expecting skill controls the mic itself: no decision is requested,
    # and the pending-reply silence-cancel path is unchanged.
    skill = FakeSkill(speech="confirm?", expects_reply=True)
    stt = FakeSTT(transcripts=["turn off for 20 minutes", ""])
    llm = FakeLLM('{"action": "end"}')
    pipeline = _pipeline(
        FakeAudioIn(6), FakeDetector(), skill, FakeTTS(), FakeOut(), AudioArbiter(),
        stt=stt, conversation_enabled=True, llm=llm, decision_enabled=True,
    )

    await pipeline.run()

    assert skill.replies == [""]  # silence still delivered to the pending skill
    assert not any(label == "decide" for (_, _, label) in llm.calls)


async def test_empty_pcm_never_reaches_stt():
    # A recorder that heard no speech returns b""; nothing is sent to whisper
    # (which hallucinates on silent audio).
    stt = FakeSTT()
    recorder = FakeRecorder(pcm=b"")
    pipeline = _pipeline(
        FakeAudioIn(6), FakeDetector(), FakeSkill(), FakeTTS(), FakeOut(),
        AudioArbiter(), stt=stt, recorder=recorder, no_speech_earcon=b"NOPE",
    )

    await pipeline.run()

    assert stt.calls == []  # silent captures (initial + retry) never transcribed


async def test_hallucination_phrase_dropped_when_quiet():
    # A near-silent capture transcribed as a known whisper artifact is treated as
    # silence: nothing is routed.
    skill = FakeSkill()
    stt = FakeSTT(transcript="Thank you. Thank you.")
    recorder = FakeRecorder(pcm=b"\x00\x00" * 100)  # rms 0: room tone
    pipeline = _pipeline(
        FakeAudioIn(6), FakeDetector(), skill, FakeTTS(), FakeOut(), AudioArbiter(),
        stt=stt, recorder=recorder,
        hallucination_phrases=["thank you"], hallucination_max_rms=300.0,
    )

    await pipeline.run()

    assert skill.handled == []  # dropped, never routed


async def test_hallucination_phrase_kept_when_loud():
    # The same phrase in a loud capture is real speech and passes through.
    skill = FakeSkill()
    stt = FakeSTT(transcript="Thank you.")
    loud = (10000).to_bytes(2, "little", signed=True) * 100
    recorder = FakeRecorder(pcm=loud)
    pipeline = _pipeline(
        FakeAudioIn(3), FakeDetector(), skill, FakeTTS(), FakeOut(), AudioArbiter(),
        stt=stt, recorder=recorder,
        hallucination_phrases=["thank you"], hallucination_max_rms=300.0,
    )

    await pipeline.run()

    assert skill.handled == [("Thank you.", "general")]


async def test_end_phrase_closes_silently():
    # Saying an end phrase ("goodbye") closes the conversation without routing it
    # to a skill — and without any farewell speech or extra LLM call.
    skill = FakeSkill(speech="it is noon")
    stt = FakeSTT(transcripts=["what time is it", "goodbye"])
    tts = FakeTTS()
    llm = FakeLLM("take care")
    pipeline = _pipeline(
        FakeAudioIn(6), FakeDetector(), skill, tts, FakeOut(), AudioArbiter(),
        stt=stt, conversation_enabled=True, llm=llm, end_phrases=["goodbye"],
    )

    await pipeline.run()

    assert skill.handled == [("what time is it", "general")]  # "goodbye" not routed
    assert tts.spoke == ["it is noon"]                        # no farewell spoken
    assert llm.calls == []                                    # no sign-off generated


async def test_silence_closes_quietly():
    # A conversation that ends on silence closes with just the descending tone:
    # nothing extra is generated or spoken.
    skill = FakeSkill()
    stt = FakeSTT(transcripts=["what time is it", ""])
    tts = FakeTTS()
    out = FakeOut()
    llm = FakeLLM("take care")
    pipeline = _pipeline(
        FakeAudioIn(6), FakeDetector(), skill, tts, out, AudioArbiter(),
        stt=stt, conversation_enabled=True, llm=llm,
        end_phrases=["goodbye"], end_earcon=b"END",
    )

    await pipeline.run()

    assert tts.spoke == ["it is noon"]   # only the reply
    assert llm.calls == []               # no farewell generated
    assert b"END" in out.played          # the descending tone still marks the end


async def test_wake_ack_delay_precedes_ack(monkeypatch):
    # A configured ack delay inserts a beat of silence before the wake ack plays,
    # so "hmm?" isn't instant. The ack still plays.
    sleeps = []

    async def _fake_sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr("assistant.core.pipeline.asyncio.sleep", _fake_sleep)
    out = FakeOut()
    pipeline = _pipeline(
        FakeAudioIn(3), FakeDetector(), FakeSkill(), FakeTTS(), out, AudioArbiter(),
        wake_earcon=b"ACK", ack_delay_s=0.3,
    )

    await pipeline.run()

    assert 0.3 in sleeps          # the beat before the ack
    assert b"ACK" in out.played   # the ack still plays after the beat


async def test_no_wake_ack_delay_by_default(monkeypatch):
    # With the default 0.0 delay, no sleep is inserted (existing turns stay instant).
    sleeps = []

    async def _fake_sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr("assistant.core.pipeline.asyncio.sleep", _fake_sleep)
    pipeline = _pipeline(
        FakeAudioIn(3), FakeDetector(), FakeSkill(), FakeTTS(), FakeOut(), AudioArbiter(),
        wake_earcon=b"ACK",  # ack_delay_s defaults to 0.0
    )

    await pipeline.run()

    assert sleeps == []


class FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class EngagingSkill(FakeSkill):
    """A skill that engages a stand-down when handled (like StandDownSkill)."""

    def __init__(self, standdown, speech="okay, standing down"):
        super().__init__(speech=speech)
        self._standdown = standdown

    async def handle(self, cmd, intent):
        self._standdown.engage(None)
        return await super().handle(cmd, intent)


class ClockAdvancingIn:
    """Yields frames, advancing the stand-down clock partway through the stream
    so a timed pause expires mid-run."""

    def __init__(self, clock, advance_at, advance_by, n):
        self._clock = clock
        self._advance_at = advance_at
        self._advance_by = advance_by
        self._n = n

    async def stream(self):
        for i in range(self._n):
            if i == self._advance_at:
                self._clock.now += self._advance_by
            yield FRAME

    def drain(self):
        pass


async def test_standdown_suppresses_wake():
    # While standing down, no frame reaches the wake detector and nothing routes.
    from assistant.core.standdown import StandDown

    detector = FakeDetector()
    skill = FakeSkill()
    tts = FakeTTS()
    standdown = StandDown()
    standdown.engage(None)
    pipeline = _pipeline(FakeAudioIn(3), detector, skill, tts, FakeOut(), AudioArbiter(),
                         standdown=standdown)

    await pipeline.run()

    assert detector.fired is False  # never processed a frame
    assert skill.handled == []
    assert tts.spoke == []


async def test_standdown_ignores_tap_to_listen():
    # A tap-to-listen while standing down is dropped, not queued for resume.
    from assistant.core.standdown import StandDown

    skill = FakeSkill()
    standdown = StandDown()
    standdown.engage(None)
    pipeline = _pipeline(FakeAudioIn(3), FakeDetector(fires=0), skill, FakeTTS(),
                         FakeOut(), AudioArbiter(), standdown=standdown)
    pipeline.request_listen()

    await pipeline.run()

    assert skill.handled == []                  # no turn started
    assert not pipeline._listen_event.is_set()  # tap consumed, not left pending


async def test_standdown_turn_speaks_confirmation_then_no_followup():
    # The turn that engages a stand-down still speaks its confirmation, but the
    # conversation ends immediately: no follow-up mic reopen.
    from assistant.core.standdown import StandDown

    standdown = StandDown()
    skill = EngagingSkill(standdown)
    tts = FakeTTS()
    recorder = FakeRecorder()
    # Scripted silence after the first turn, so a missing gate fails the
    # start_timeouts assertion instead of conversing forever.
    stt = FakeSTT(transcripts=["stand down", ""])
    pipeline = _pipeline(FakeAudioIn(6), FakeDetector(), skill, tts, FakeOut(),
                         AudioArbiter(), recorder=recorder, conversation_enabled=True,
                         stt=stt, standdown=standdown)

    await pipeline.run()

    assert tts.spoke == ["okay, standing down"]  # confirmation spoken
    assert len(skill.handled) == 1               # handled exactly once
    assert recorder.start_timeouts == [None]     # no follow-up capture


class TapAudioIn(FakeAudioIn):
    """FakeAudioIn that also accepts a mic tap, like MicHub."""

    def __init__(self, n):
        super().__init__(n)
        self.tap = None
        self.tap_clears = 0

    def set_tap(self, tap):
        self.tap = tap

    def clear_tap(self):
        self.tap = None
        self.tap_clears += 1


class BargingOut(FakeOut):
    """FakeOut that injects mic frames into the audio-in tap while 'playing',
    simulating the user speaking over the reply (as the MicHub pump would)."""

    def __init__(self, audio_in, frames_per_play=3):
        super().__init__()
        self._audio_in = audio_in
        self._frames = frames_per_play

    async def play(self, audio):
        await super().play(audio)
        tap = self._audio_in.tap
        if tap is not None:
            for _ in range(self._frames):
                tap(FRAME)


class ScriptedDetector:
    """WakeEvents from a scripted score queue (None = no event that frame)."""

    def __init__(self, scores):
        self._scores = deque(scores)
        self.resets = 0

    def process(self, frame):
        score = self._scores.popleft() if self._scores else None
        return WakeEvent("test", score) if score is not None else None

    def reset(self):
        self.resets += 1


async def test_barge_in_cuts_reply_and_recaptures_without_ack():
    audio_in = TapAudioIn(6)
    out = BargingOut(audio_in, frames_per_play=3)
    skill = FakeSkill(speech="First sentence. Second sentence.")
    tts = FakeTTS()
    recorder = FakeRecorder()
    # The wake fires, then the 3 tap frames during playback all clear the gate.
    detector = ScriptedDetector([0.9, 0.9, 0.9, 0.9])
    stt = FakeSTT(transcripts=["tell me a story", ""])
    pipeline = _pipeline(audio_in, detector, skill, tts, out, AudioArbiter(),
                         recorder=recorder, stt=stt, wake_earcon=b"ACK",
                         conversation_enabled=True, barge_in_enabled=True,
                         barge_in_threshold=0.8, barge_in_trigger_frames=3)

    await pipeline.run()

    assert out.stops == 1                           # playback cut mid-reply
    assert tts.spoke == ["First sentence."]         # second sentence never synthesized
    assert out.played.count(b"ACK") == 1            # no wake ack on the barge reopen
    assert recorder.start_timeouts == [None, 6000]  # mic reopened with the follow-up window
    assert audio_in.tap is None                     # tap removed after speaking


async def test_barge_in_disabled_ignores_wake_during_speak():
    audio_in = TapAudioIn(3)
    out = BargingOut(audio_in)
    skill = FakeSkill(speech="First. Second.")
    tts = FakeTTS()
    pipeline = _pipeline(audio_in, FakeDetector(), skill, tts, out, AudioArbiter())

    await pipeline.run()

    assert out.stops == 0
    assert tts.spoke == ["First.", "Second."]  # full reply spoken
    assert audio_in.tap is None                # tap never installed
    assert audio_in.tap_clears == 0


async def test_barge_gate_requires_raised_score():
    # Wake events during playback that clear the wake threshold but not the barge
    # threshold never barge (residual speaker echo must not cut the reply).
    audio_in = TapAudioIn(3)
    out = BargingOut(audio_in, frames_per_play=5)
    skill = FakeSkill(speech="One long reply.")
    tts = FakeTTS()
    detector = ScriptedDetector([0.9] + [0.7] * 5)
    pipeline = _pipeline(audio_in, detector, skill, tts, out, AudioArbiter(),
                         barge_in_enabled=True, barge_in_threshold=0.8,
                         barge_in_trigger_frames=3)

    await pipeline.run()

    assert out.stops == 0
    assert tts.spoke == ["One long reply."]


async def test_barge_gate_requires_consecutive_hits():
    # A sub-threshold event mid-streak resets the count: 2 hits, a miss, 2 hits
    # never reaches trigger_frames=3.
    audio_in = TapAudioIn(3)
    out = BargingOut(audio_in, frames_per_play=5)
    skill = FakeSkill(speech="One long reply.")
    tts = FakeTTS()
    detector = ScriptedDetector([0.9, 0.9, 0.9, 0.7, 0.9, 0.9])
    pipeline = _pipeline(audio_in, detector, skill, tts, out, AudioArbiter(),
                         barge_in_enabled=True, barge_in_threshold=0.8,
                         barge_in_trigger_frames=3)

    await pipeline.run()

    assert out.stops == 0
    assert tts.spoke == ["One long reply."]


class BusyAnnouncementIn:
    """Yields ``busy_frames`` frames while another holder owns the arbiter (a
    proactive announcement), then frees it and yields ``tail`` more."""

    def __init__(self, arbiter, busy_frames=3, tail=3):
        self._arbiter = arbiter
        self._busy = busy_frames
        self._tail = tail

    async def stream(self):
        await self._arbiter._lock.acquire()
        for _ in range(self._busy):
            yield FRAME
        self._arbiter._lock.release()
        for _ in range(self._tail):
            yield FRAME

    def drain(self):
        pass

    def set_tap(self, tap):
        pass

    def clear_tap(self):
        pass


async def test_announcement_barge_stops_playback_and_opens_turn():
    # A gated wake while a reminder announcement plays (arbiter busy) cuts the
    # announcer's playback and opens a manual-listen turn once the arbiter frees.
    arbiter = AudioArbiter()
    audio_in = BusyAnnouncementIn(arbiter, busy_frames=3, tail=3)
    detector = ScriptedDetector([0.9, 0.9, 0.9])  # scored during the busy frames
    out = FakeOut()
    skill = FakeSkill()
    pipeline = _pipeline(audio_in, detector, skill, FakeTTS(), out, arbiter,
                         barge_in_enabled=True, barge_in_threshold=0.8,
                         barge_in_trigger_frames=3, barge_in_announcements=True)

    await pipeline.run()

    assert out.stops == 1  # the announcement was cut
    assert skill.handled == [("what time is it", "general")]  # turn followed


async def test_announcement_barge_off_keeps_dropping_frames():
    # barge_in.announcements defaults off: the busy branch must keep dropping
    # frames (never score the announcement's own audio), even with barge_in on.
    arbiter = AudioArbiter()
    audio_in = BusyAnnouncementIn(arbiter, busy_frames=3, tail=0)
    detector = ScriptedDetector([0.9, 0.9, 0.9])
    out = FakeOut()
    skill = FakeSkill()
    pipeline = _pipeline(audio_in, detector, skill, FakeTTS(), out, arbiter,
                         barge_in_enabled=True, barge_in_threshold=0.8,
                         barge_in_trigger_frames=3)

    await pipeline.run()

    assert out.stops == 0
    assert skill.handled == []


async def test_standdown_emits_paused_once_then_idle_on_expiry():
    # Entering the pause emits one "paused" (with remaining); expiry of the timer
    # emits one "idle" — edge-triggered, not per frame.
    from assistant.core.standdown import StandDown

    clock = FakeClock()
    standdown = StandDown(clock=clock)
    standdown.engage(60)
    emitter = RecordingEmitter()
    audio_in = ClockAdvancingIn(clock, advance_at=3, advance_by=120, n=6)
    pipeline = _pipeline(audio_in, FakeDetector(fires=0), FakeSkill(), FakeTTS(),
                         FakeOut(), AudioArbiter(), state_emitter=emitter,
                         standdown=standdown)

    await pipeline.run()

    assert emitter.states == ["idle", "paused", "idle"]
    assert emitter.fields[1] == {"remaining": 60}
