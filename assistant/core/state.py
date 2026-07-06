"""Daemon -> TUI state feed.

The pipeline is an implicit state machine (idle -> listening -> thinking ->
speaking). The monitor TUI supervises the daemon and only *reads its stdout*, so
we surface turn state the same way: a marker line printed to stdout alongside the
logs. This keeps the dependency one-directional (`tui` reads `assistant`, never
the reverse) and needs no new transport.

Each line is ``@@STATE {json}\\n`` where the JSON carries at least ``state`` and,
for the live level meter, a ``level`` (int16 RMS). The feed is best-effort: a
write failure must never break a turn, so every emit swallows its errors.

The reader side (parsing these lines back into payloads) lives in the TUI,
``tui/logparse.py``, to keep the ``tui`` -> ``assistant`` dependency one-directional.
"""

from __future__ import annotations

import json
import logging
import sys
from typing import TextIO

log = logging.getLogger(__name__)

MARKER = "@@STATE "


class StateEmitter:
    """Prints pipeline state/level to a stream (stdout in production)."""

    def __init__(self, stream: TextIO | None = None) -> None:
        self._stream = stream if stream is not None else sys.stdout
        self._state = "idle"

    def state(self, name: str, **fields: object) -> None:
        self._state = name
        self._write({"state": name, **fields})

    def level(self, rms: float) -> None:
        # A level tick is always tagged with the current state so the TUI can draw
        # the meter under whichever screen the state selected.
        self._write({"state": self._state, "level": round(float(rms))})

    def _write(self, payload: dict) -> None:
        try:
            self._stream.write(MARKER + json.dumps(payload) + "\n")
            self._stream.flush()
        except Exception as exc:  # noqa: BLE001 - the feed is decoration, never fatal
            log.debug("state feed write failed: %s", exc)


class NullStateEmitter:
    """No-op emitter: the default when nothing is listening (standalone daemon,
    unit tests). Keeps the pipeline's emit calls unconditional."""

    def state(self, name: str, **fields: object) -> None:
        pass

    def level(self, rms: float) -> None:
        pass
