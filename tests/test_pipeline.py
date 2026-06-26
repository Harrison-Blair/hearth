from assistant.core.arbiter import AudioArbiter
from assistant.core.events import SkillResult, WakeEvent
from assistant.core.pipeline import VoicePipeline
from assistant.nlu.keyphrase_router import KeyphraseRouter
from assistant.skills.base import Skill, SkillRegistry

FRAME = bytes(2560)


class FakeAudioIn:
    def __init__(self, n):
        self._n = n

    async def stream(self):
        for _ in range(self._n):
            yield FRAME


class FakeDetector:
    def __init__(self):
        self.fired = False
        self.resets = 0

    def process(self, frame):
        if not self.fired:
            self.fired = True
            return WakeEvent("test", 0.9)
        return None

    def reset(self):
        self.resets += 1


class FakeRecorder:
    def __init__(self):
        self.prefixes = []

    async def record(self, frames, prefix=b""):
        self.prefixes.append(prefix)
        await frames.__anext__()  # consume one frame, like a real capture
        return b"\x00\x00"


class FakeSTT:
    def __init__(self, transcript="what time is it"):
        self.calls = []
        self._transcript = transcript

    async def transcribe(self, audio):
        self.calls.append(audio)
        return self._transcript


class RaisingSkill(Skill):
    name = "raising"
    intents = {"general"}

    async def handle(self, cmd, intent):
        raise RuntimeError("skill boom")


class FakeSkill(Skill):
    name = "fake"
    intents = {"general"}

    def __init__(self):
        self.handled = []

    async def handle(self, cmd, intent):
        self.handled.append((cmd.text, intent.type))
        return SkillResult(speech="it is noon")


class FakeTTS:
    def __init__(self):
        self.spoke = []

    async def synthesize(self, text):
        self.spoke.append(text)
        return b"AUDIO"


class FakeOut:
    def __init__(self):
        self.played = []

    async def play(self, audio):
        self.played.append(audio)


def _pipeline(audio_in, detector, skill, tts, out, arbiter, *, stt=None,
              no_speech_earcon=b"", wake_earcon=b""):
    registry = SkillRegistry()
    registry.register(skill, default=True)
    return VoicePipeline(
        audio_in, detector, FakeRecorder(), stt or FakeSTT(),
        KeyphraseRouter(), registry, tts, out, arbiter,
        no_speech_earcon=no_speech_earcon,
        wake_earcon=wake_earcon,
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
