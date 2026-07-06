"""Unit tests for the daemon-side ControlChannel line protocol (stdin verbs)."""

import asyncio

from assistant.core.arbiter import AudioArbiter
from assistant.core.control import ControlChannel


class FakePipeline:
    def __init__(self):
        self.texts = []
        self.listens = 0
        self.cancels = 0

    async def submit_text(self, text):
        self.texts.append(text)

    def request_listen(self):
        self.listens += 1

    def cancel(self):
        self.cancels += 1


class FakeOut:
    def __init__(self):
        self.volumes = []
        self.stops = 0

    def set_volume(self, v):
        self.volumes.append(v)

    def stop(self):
        self.stops += 1


class FakeSpeaker:
    def __init__(self):
        self.said = []  # (text, length_scale) pairs

    async def say(self, text, length_scale=None):
        self.said.append((text, length_scale))


def _channel():
    p, out, speaker = FakePipeline(), FakeOut(), FakeSpeaker()
    return ControlChannel(p, out, speaker, AudioArbiter()), p, out


async def test_text_verb_submits_command():
    ch, p, _ = _channel()
    await ch.dispatch("TEXT what time is it")
    assert p.texts == ["what time is it"]


async def test_set_volume_verb():
    ch, _, out = _channel()
    await ch.dispatch("SET audio.output_volume 0.3")
    assert out.volumes == [0.3]


async def test_listen_verb_requests_a_turn():
    ch, p, _ = _channel()
    await ch.dispatch("LISTEN")
    assert p.listens == 1


async def test_cancel_verb_cancels_capture():
    ch, p, _ = _channel()
    await ch.dispatch("CANCEL")
    assert p.cancels == 1


async def test_stop_verb_barges_in_on_playback():
    ch, _, out = _channel()
    await ch.dispatch("STOP")
    assert out.stops == 1


async def test_verbs_are_case_insensitive():
    ch, p, _ = _channel()
    await ch.dispatch("listen")
    assert p.listens == 1


async def test_say_verb_speaks_plain_text():
    ch, _, _ = _channel()
    await ch.dispatch("SAY hello there")
    assert ch._speaker.said == [("hello there", None)]  # default rate


async def test_say_verb_parses_rate_prefix():
    ch, _, _ = _channel()
    await ch.dispatch("SAY 1.3|hello there")
    assert ch._speaker.said == [("hello there", 1.3)]  # rate applied, text after |


async def test_say_verb_non_numeric_prefix_is_all_text():
    ch, _, _ = _channel()
    await ch.dispatch("SAY foo|bar")  # prefix isn't a rate -> whole line is text
    assert ch._speaker.said == [("foo|bar", None)]


async def test_say_verb_without_speaker_is_ignored():
    ch = ControlChannel(FakePipeline(), FakeOut())  # no speaker wired
    await ch.dispatch("SAY hi")  # no raise


async def test_unknown_verb_is_ignored():
    ch, p, out = _channel()
    await ch.dispatch("FLOOP nonsense")  # no raise
    assert p.texts == [] and p.listens == 0 and p.cancels == 0 and out.stops == 0


async def test_say_waits_for_arbiter_before_speaking():
    # SAY must hold the AudioArbiter so a voice test cannot play over an
    # in-progress pipeline reply. While another holder owns the arbiter, the
    # speaker must not be called.
    arbiter = AudioArbiter()
    speaker = FakeSpeaker()
    ch = ControlChannel(FakePipeline(), FakeOut(), speaker, arbiter)
    async with arbiter.hold("pipeline"):
        say = asyncio.create_task(ch.dispatch("SAY hello"))
        await asyncio.sleep(0)  # let the task run up to the arbiter
        assert speaker.said == []  # blocked: reply still owns the audio device
    await say
    assert speaker.said == [("hello", None)]  # spoke once the hold released
