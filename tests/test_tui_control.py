from assistant.core.control import ControlChannel


class FakePipeline:
    def __init__(self):
        self.texts = []

    async def submit_text(self, text):
        self.texts.append(text)


class FakeOut:
    def __init__(self):
        self.volumes = []

    def set_volume(self, v):
        self.volumes.append(v)


def _channel():
    pipeline, out = FakePipeline(), FakeOut()
    return ControlChannel(pipeline, out), pipeline, out


async def test_text_command_injects_transcript():
    chan, pipeline, _ = _channel()
    await chan.dispatch("TEXT what time is it\n")
    assert pipeline.texts == ["what time is it"]


async def test_set_volume_command_applies_live():
    chan, _, out = _channel()
    await chan.dispatch("SET audio.output_volume 0.0")
    assert out.volumes == [0.0]


async def test_unknown_command_is_ignored():
    chan, pipeline, out = _channel()
    await chan.dispatch("WAT something")
    await chan.dispatch("")
    await chan.dispatch("SET other.key 1.0")  # not live-settable
    await chan.dispatch("SET audio.output_volume notanumber")  # bad value
    assert pipeline.texts == []
    assert out.volumes == []
