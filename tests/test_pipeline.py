from assistant.core.events import WakeEvent
from assistant.core.pipeline import VoicePipeline

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
    def __init__(self):
        self.calls = []

    async def transcribe(self, audio):
        self.calls.append(audio)
        return "what time is it"


async def test_wake_triggers_record_and_transcribe():
    stt = FakeSTT()
    detector = FakeDetector()
    pipeline = VoicePipeline(FakeAudioIn(3), detector, FakeRecorder(), stt)

    await pipeline.run()

    assert stt.calls == [b"\x00\x00"]  # transcribed exactly once
    assert detector.resets == 1  # reset after handling
