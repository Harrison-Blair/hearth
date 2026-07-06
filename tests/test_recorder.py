from collections import deque

from assistant.audio.recorder import VadRecorder

FRAME = bytes(2560)  # 1280 int16 samples = 80ms @ 16kHz


class FakeVad:
    """Returns scripted is_speech() results, defaulting to silence when empty."""

    def __init__(self, script):
        self._script = deque(script)

    def is_speech(self, chunk, sample_rate):
        return self._script.popleft() if self._script else False


async def _drain(frames):
    for f in frames:
        yield f


async def test_ends_after_trailing_silence():
    rec = VadRecorder(silence_ms=40, start_timeout_ms=100000, max_ms=100000)
    # frame1: 4 voiced sub-frames; frame2: silence -> 40ms silence ends it.
    rec._vad = FakeVad([True, True, True, True, False, False])
    pcm = await rec.record(_drain([FRAME, FRAME, FRAME]))
    assert pcm == FRAME * 2  # stopped during the second frame


async def test_start_timeout_when_no_speech():
    rec = VadRecorder(silence_ms=200, start_timeout_ms=80, max_ms=100000)
    rec._vad = FakeVad([])  # all silence
    pcm = await rec.record(_drain([FRAME, FRAME, FRAME]))
    # 80ms timeout = 4 sub-frames = within the first 80ms frame.
    assert pcm == FRAME


async def test_cancel_event_abandons_capture():
    import asyncio

    rec = VadRecorder(silence_ms=200, start_timeout_ms=100000, max_ms=100000)
    rec._vad = FakeVad([True, True, True, True])  # would otherwise be speech
    cancel = asyncio.Event()
    cancel.set()
    pcm = await rec.record(_drain([FRAME, FRAME]), cancel_event=cancel)
    assert pcm == b""  # abandoned before collecting anything


async def test_on_level_called_per_frame():
    # The level meter gets one RMS reading per input frame consumed.
    rec = VadRecorder(silence_ms=40, start_timeout_ms=100000, max_ms=100000)
    rec._vad = FakeVad([True, True, True, True, False, False])
    levels = []
    await rec.record(_drain([FRAME, FRAME, FRAME]), on_level=levels.append)
    assert len(levels) == 2  # consumed 2 frames before trailing silence ended it
    assert all(isinstance(x, float) for x in levels)


async def test_start_timeout_override_wins_over_constructor():
    # Constructor default would time out after the first frame; the per-call
    # override extends it, so silence runs into the second frame.
    rec = VadRecorder(silence_ms=200, start_timeout_ms=80, max_ms=100000)
    rec._vad = FakeVad([])  # all silence
    pcm = await rec.record(_drain([FRAME, FRAME, FRAME]), start_timeout_ms=160)
    # 160ms timeout = 8 sub-frames = into the second 80ms frame.
    assert pcm == FRAME * 2
