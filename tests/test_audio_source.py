"""Audio-source seam tests (FTHR-028, FC-11 / FC-15).

The injectable audio source: a live-device implementation that must acquire the
input **non-exclusively** so PLM-009 playback can run concurrently, and a
supplied-frames implementation the surface tests drive. No real device is
touched here -- the device open is asserted through an injected stream factory.
"""
from __future__ import annotations


def test_input_device_acquired_non_exclusively():
    """The live source opens the input device in a non-exclusive mode.

    Asserts on the acquisition parameter passed to the stream factory, not a
    real device: the source must name its acquisition mode as non-exclusive so
    the mic stays usable while audio is played (PLM-008 FC-15, AC-17). A source
    that opened exclusively -- or left the mode unnamed -- fails here.
    """
    from hearth.audio.source import NON_EXCLUSIVE, LiveAudioSource

    captured: dict = {}

    def fake_stream_factory(**kwargs):
        captured.update(kwargs)
        return object()

    source = LiveAudioSource(stream_factory=fake_stream_factory)
    assert source.acquisition_mode == NON_EXCLUSIVE

    source._open_stream()
    assert captured.get("acquisition") == NON_EXCLUSIVE


async def test_supplied_frames_source_yields_in_order():
    """The test-drivable source yields exactly the frames it was handed, in
    order -- the seam the surface tests feed."""
    from hearth.audio.source import SuppliedFramesSource

    source = SuppliedFramesSource(["a", "b", "c"])
    seen = [frame async for frame in source.frames()]
    assert seen == ["a", "b", "c"]
