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


def _pipeline(audio_in, detector, skill, tts, out, arbiter, *, stt=None, no_speech_earcon=b""):
    registry = SkillRegistry()
    registry.register(skill, default=True)
    return VoicePipeline(
        audio_in, detector, FakeRecorder(), stt or FakeSTT(),
        KeyphraseRouter(), registry, tts, out, arbiter,
        no_speech_earcon=no_speech_earcon,
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


async def test_skill_exception_is_spoken_and_loop_survives():
    detector = FakeDetector()
    tts = FakeTTS()
    out = FakeOut()
    pipeline = _pipeline(FakeAudioIn(3), detector, RaisingSkill(), tts, out, AudioArbiter())

    await pipeline.run()

    assert tts.spoke == ["Sorry, something went wrong."]
    assert out.played == [b"AUDIO"]
    assert detector.resets == 1  # turn completed; loop kept going
