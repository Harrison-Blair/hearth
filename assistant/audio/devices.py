"""Audio device selection.

Defaults to the system default input/output, but honours a config override
given as an integer index or a substring of the device name. The same build
then runs on the dev desktop and the Pi with only a config change.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import sounddevice as sd

log = logging.getLogger(__name__)

# Virtual devices that follow the system default sink/source AND resample to
# arbitrary rates. Preferred for auto-detection so playback/capture "just works"
# regardless of what raw hardware rate a device exposes (desktop + Pi alike).
# pulse/pipewire (the PortAudio<->PipeWire bridges) reliably track the system
# default source; the bare ALSA "default" PCM can route elsewhere, so it's last.
PREFERRED_DEFAULTS = ("pulse", "pipewire", "default")


@dataclass
class DeviceInfo:
    index: int
    name: str

    def __str__(self) -> str:
        return f"[{self.index}] {self.name}"


def _resolve(spec: str | int | None, kind: str) -> DeviceInfo:
    """Resolve a config spec (None | index | name substring) to a device."""
    channel_key = f"max_{kind}_channels"
    devices = sd.query_devices()

    if spec is None:
        # Prefer a resampling virtual default (pulse/pipewire/default).
        for name in PREFERRED_DEFAULTS:
            for i, dev in enumerate(devices):
                if dev["name"].lower() == name and dev[channel_key] > 0:
                    return DeviceInfo(i, dev["name"])
        # Otherwise PortAudio's registered default for this direction.
        idx = sd.default.device[0 if kind == "input" else 1]
        if idx is not None and idx >= 0:
            return DeviceInfo(idx, sd.query_devices(idx)["name"])
        # Last resort: first capable device.
        for i, dev in enumerate(devices):
            if dev[channel_key] > 0:
                return DeviceInfo(i, dev["name"])
        raise RuntimeError(f"no {kind} device available")

    if isinstance(spec, int):
        return DeviceInfo(spec, sd.query_devices(spec)["name"])

    needle = spec.lower()
    for i, dev in enumerate(devices):
        if needle in dev["name"].lower() and dev[channel_key] > 0:
            return DeviceInfo(i, dev["name"])
    raise ValueError(f"no {kind} device matching {spec!r}")


@dataclass
class DeviceSelection:
    input: DeviceInfo
    output: DeviceInfo


def select_devices(audio_config) -> DeviceSelection:
    """Resolve and log the input/output devices from audio config."""
    selection = DeviceSelection(
        input=_resolve(audio_config.input, "input"),
        output=_resolve(audio_config.output, "output"),
    )
    log.info("Audio input device:  %s", selection.input)
    log.info("Audio output device: %s", selection.output)
    return selection
