"""StandDown — shared "stop listening and stay silent" state.

Engaged by the stand-down skill (voice) and cleared by the TUI's Resume button
(RESUME control verb) or a deadline. Every consumer (pipeline frame loop,
reminder scheduler, calendar watcher) checks ``active`` on its own tick, so a
timed stand-down expires without any background task. In-memory only: a daemon
restart clears it.
"""

from __future__ import annotations

import time
from typing import Callable


class StandDown:
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._engaged = False
        self._deadline: float | None = None

    def engage(self, seconds: float | None) -> None:
        """Go silent; ``seconds=None`` means until an explicit resume()."""
        self._engaged = True
        self._deadline = None if seconds is None else self._clock() + seconds

    def resume(self) -> None:
        self._engaged = False
        self._deadline = None

    @property
    def active(self) -> bool:
        if not self._engaged:
            return False
        if self._deadline is not None and self._clock() >= self._deadline:
            self.resume()  # latch off so remaining/active stay consistent
            return False
        return True

    @property
    def remaining(self) -> float | None:
        """Seconds until auto-resume; None when inactive or indefinite."""
        if not self.active or self._deadline is None:
            return None
        return self._deadline - self._clock()
