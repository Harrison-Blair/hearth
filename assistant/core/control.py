"""Control channel: line commands read from stdin while the daemon runs.

The monitor TUI (`tui`) supervises the daemon as a child process and
writes newline commands to its stdin. This lets the TUI drive the live daemon
without a restart:

    TEXT <utterance>           inject a typed command as if it were transcribed
    SET audio.output_volume V  change playback gain (mute = 0.0) immediately

Running the daemon standalone in a terminal is unaffected: stdin simply blocks
until EOF (Ctrl-D), and any stray input is ignored.
"""

from __future__ import annotations

import asyncio
import logging
import sys

from assistant.audio.sounddevice_io import SoundDeviceOut
from assistant.core.pipeline import VoicePipeline

log = logging.getLogger(__name__)


class ControlChannel:
    def __init__(self, pipeline: VoicePipeline, out: SoundDeviceOut) -> None:
        self._pipeline = pipeline
        self._out = out

    async def run(self) -> None:
        """Read stdin line by line (off-thread) and dispatch until EOF."""
        while True:
            line = await asyncio.to_thread(sys.stdin.readline)
            if line == "":  # EOF: stdin closed (e.g. TUI child terminated)
                log.debug("control channel: stdin closed")
                return
            await self.dispatch(line)

    async def dispatch(self, line: str) -> None:
        """Parse and act on one command line. The unit-tested surface."""
        line = line.strip()
        if not line:
            return
        verb, _, rest = line.partition(" ")
        verb = verb.upper()
        if verb == "TEXT":
            await self._pipeline.submit_text(rest)
        elif verb == "SET":
            self._set(rest)
        else:
            log.debug("control channel: ignoring unknown command %r", line)

    def _set(self, rest: str) -> None:
        key, _, value = rest.partition(" ")
        if key == "audio.output_volume":
            try:
                self._out.set_volume(float(value))
            except ValueError:
                log.debug("control channel: bad volume %r", value)
        else:
            log.debug("control channel: %r is not live-settable", key)
