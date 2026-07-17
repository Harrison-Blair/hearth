"""The injectable audio-source seam (FC-11).

A source yields audio frames the surface routes through its stages. Two
implementations ship here:

- `LiveAudioSource` -- opens the real input device. It acquires the device
  **non-exclusively** (`NON_EXCLUSIVE`) so PLM-009 playback can run concurrently
  and the mic stays live while audio is played (FC-15). In CI this is never
  opened for real; the acquisition mode is asserted structurally via an injected
  stream factory (see `test_audio_source.py`) and validated on real hardware by
  FTHR-033's manual smoke.
- `SuppliedFramesSource` -- yields a caller-provided list of frames; the seam the
  spine tests feed.

The source is injected into the surface, so a real device is never a test
dependency.
"""
from __future__ import annotations

import asyncio
from typing import AsyncIterator, Protocol, runtime_checkable

# The device is opened in a **non-exclusive** (shared-access) mode: the mic stays
# usable by other clients while hearth captures, which is what lets playback run
# concurrently with capture (PLM-008 FC-15 / PLM-009 barge-in). PortAudio/ALSA
# open shared by default; we name the mode explicitly and never request an
# exclusive host-API setting, so a reviewer can see the choice at a glance.
NON_EXCLUSIVE = "non-exclusive"


@runtime_checkable
class AudioSource(Protocol):
    """Yields audio frames until the stream ends."""

    def frames(self) -> AsyncIterator: ...


class SuppliedFramesSource:
    """Yields a fixed list of frames -- the test-drivable source.

    With `pace=True`, it yields to the event loop between frames so a consumer
    and a concurrent submitter interleave deterministically (used by the duplex
    test); otherwise it yields eagerly.
    """

    def __init__(self, frames, *, pace: bool = False) -> None:
        self._frames = list(frames)
        self._pace = pace

    async def frames(self) -> AsyncIterator:
        for frame in self._frames:
            if self._pace:
                await asyncio.sleep(0)
            yield frame


def _default_input_stream(*, acquisition, **kwargs):
    """Build a real `sounddevice` input stream.

    `acquisition` is `NON_EXCLUSIVE`: PortAudio/ALSA open shared by default, so we
    pass no exclusive host-API `extra_settings`. The parameter is threaded through
    so the acquisition intent is explicit and assertable without a real device.
    `sounddevice` is imported lazily so importing this module (and running the
    spine's tests) never requires PortAudio.
    """
    import sounddevice  # noqa: PLC0415 -- lazy: PortAudio not needed for tests

    assert acquisition == NON_EXCLUSIVE
    return sounddevice.InputStream(**kwargs)


class LiveAudioSource:
    """Captures from the real input device, non-exclusively (FC-15)."""

    acquisition_mode = NON_EXCLUSIVE

    def __init__(
        self,
        *,
        samplerate: int = 16000,
        channels: int = 1,
        blocksize: int = 512,
        device=None,
        stream_factory=None,
    ) -> None:
        self._samplerate = samplerate
        self._channels = channels
        self._blocksize = blocksize
        self._device = device
        self._stream_factory = stream_factory or _default_input_stream

    def _open_stream(self):
        return self._stream_factory(
            samplerate=self._samplerate,
            channels=self._channels,
            blocksize=self._blocksize,
            device=self._device,
            acquisition=self.acquisition_mode,
        )

    async def frames(self) -> AsyncIterator:
        stream = self._open_stream()
        stream.start()
        try:
            while True:
                # `stream.read` blocks on the PortAudio thread; offload it so the
                # capture task never freezes the event loop (and the submit task
                # keeps running -- the duplex property, FC-15).
                block, _overflowed = await asyncio.to_thread(stream.read, self._blocksize)
                yield block
        finally:
            stream.stop()
            stream.close()
