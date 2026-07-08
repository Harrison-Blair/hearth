import asyncio

from assistant.audio.mic_hub import MicHub


class QueueIn:
    """AudioIn fake fed frame-by-frame from the test; None ends the stream."""

    def __init__(self):
        self.q = asyncio.Queue()
        self.drains = 0

    async def stream(self):
        while True:
            frame = await self.q.get()
            if frame is None:
                return
            yield frame

    def drain(self):
        self.drains += 1


async def _next(stream):
    return await asyncio.wait_for(stream.__anext__(), timeout=1.0)


async def test_pump_delivers_inner_frames_in_order():
    inner = QueueIn()
    hub = MicHub(inner)
    stream = hub.stream()
    for frame in (b"a", b"b", b"c"):
        inner.q.put_nowait(frame)

    assert [await _next(stream), await _next(stream), await _next(stream)] == [b"a", b"b", b"c"]


async def test_tap_sees_frames_while_set_and_none_after_clear():
    inner = QueueIn()
    hub = MicHub(inner)
    stream = hub.stream()
    taps = []
    hub.set_tap(taps.append)

    inner.q.put_nowait(b"a")
    assert await _next(stream) == b"a"
    assert taps == [b"a"]

    hub.clear_tap()
    inner.q.put_nowait(b"b")
    assert await _next(stream) == b"b"
    assert taps == [b"a"]


async def test_processor_transforms_frames_before_queue_and_tap():
    inner = QueueIn()
    hub = MicHub(inner, processor=lambda frame: frame.upper())
    stream = hub.stream()
    taps = []
    hub.set_tap(taps.append)

    inner.q.put_nowait(b"abc")
    assert await _next(stream) == b"ABC"
    assert taps == [b"ABC"]


async def test_drain_empties_buffer_and_forwards_to_inner():
    inner = QueueIn()
    hub = MicHub(inner)
    stream = hub.stream()
    inner.q.put_nowait(b"stale-1")
    inner.q.put_nowait(b"stale-2")
    # Let the pump move both frames into the hub's buffer before draining.
    while inner.q.qsize():
        await asyncio.sleep(0)

    hub.drain()
    inner.q.put_nowait(b"fresh")

    assert await _next(stream) == b"fresh"
    assert inner.drains == 1


async def test_tap_error_does_not_kill_the_pump():
    inner = QueueIn()
    hub = MicHub(inner)
    stream = hub.stream()

    def bad_tap(frame):
        raise RuntimeError("tap boom")

    hub.set_tap(bad_tap)
    inner.q.put_nowait(b"a")

    assert await _next(stream) == b"a"  # frame still delivered


async def test_full_buffer_drops_oldest_frame():
    inner = QueueIn()
    hub = MicHub(inner, maxsize=2)
    stream = hub.stream()
    for frame in (b"a", b"b", b"c"):
        inner.q.put_nowait(frame)
    while inner.q.qsize():
        await asyncio.sleep(0)

    assert await _next(stream) == b"b"  # b"a" was dropped, freshest frames kept
    assert await _next(stream) == b"c"
