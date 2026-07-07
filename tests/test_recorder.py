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
    # No speech ever started: return empty so nothing is transcribed.
    assert pcm == b""


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
    # override extends it, so the recorder keeps listening into the second
    # frame (observed via on_level, since a silent capture returns empty).
    rec = VadRecorder(silence_ms=200, start_timeout_ms=80, max_ms=100000)
    rec._vad = FakeVad([])  # all silence
    levels = []
    pcm = await rec.record(
        _drain([FRAME, FRAME, FRAME]), start_timeout_ms=160, on_level=levels.append
    )
    assert pcm == b""
    # 160ms timeout = 8 sub-frames = into the second 80ms frame.
    assert len(levels) == 2


async def test_single_voiced_blip_below_min_speech_returns_empty():
    # One 20ms voiced blip (chair creak) must not count as speech when
    # min_speech_ms requires more; the start timeout then closes the capture.
    rec = VadRecorder(silence_ms=40, start_timeout_ms=200, max_ms=100000, min_speech_ms=60)
    rec._vad = FakeVad([True])  # a lone blip, then silence
    pcm = await rec.record(_drain([FRAME, FRAME, FRAME]))
    assert pcm == b""


async def test_min_speech_reached_records_normally():
    rec = VadRecorder(silence_ms=40, start_timeout_ms=100000, max_ms=100000, min_speech_ms=60)
    # 60ms of voiced sub-frames crosses the gate; trailing silence then ends it.
    rec._vad = FakeVad([True, True, True, True, False, False])
    pcm = await rec.record(_drain([FRAME, FRAME, FRAME]))
    assert pcm == FRAME * 2


async def test_max_ms_without_speech_returns_empty():
    rec = VadRecorder(silence_ms=200, start_timeout_ms=100000, max_ms=80)
    rec._vad = FakeVad([])  # all silence up to the hard cap
    pcm = await rec.record(_drain([FRAME, FRAME]))
    assert pcm == b""
