import pytest

from assistant.audio import devices
from assistant.core.config import AudioConfig

FAKE_DEVICES = [
    {"name": "Built-in Microphone", "max_input_channels": 2, "max_output_channels": 0},
    {"name": "Built-in Output", "max_input_channels": 0, "max_output_channels": 2},
    {"name": "USB Headset", "max_input_channels": 1, "max_output_channels": 2},
]


class FakeSd:
    class default:
        device = [0, 1]

    @staticmethod
    def query_devices(idx=None):
        if idx is None:
            return FAKE_DEVICES
        return FAKE_DEVICES[idx]


@pytest.fixture(autouse=True)
def patch_sd(monkeypatch):
    monkeypatch.setattr(devices, "sd", FakeSd)


def test_default_devices():
    sel = devices.select_devices(AudioConfig(input=None, output=None))
    assert sel.input.index == 0
    assert sel.output.index == 1


def test_index_override():
    sel = devices.select_devices(AudioConfig(input=2, output=2))
    assert sel.input.name == "USB Headset"
    assert sel.output.name == "USB Headset"


def test_name_substring_match():
    sel = devices.select_devices(AudioConfig(input="headset", output="output"))
    assert sel.input.index == 2
    assert sel.output.index == 1


def test_no_match_raises():
    with pytest.raises(ValueError):
        devices.select_devices(AudioConfig(input="nonexistent", output=None))
