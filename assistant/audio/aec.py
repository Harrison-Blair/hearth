"""Acoustic echo cancellation (Speex) for barge-in.

While the assistant speaks, the mic hears the speaker; without AEC the wake
detector scores that echo and barge-in has to hide behind a raised threshold.
The canceller subtracts a *far-end reference* (what we are playing) from the
*near-end signal* (what the mic hears), so the wake word stays audible over the
assistant's own voice.

Wiring (app.py): ``SoundDeviceOut`` feeds every clip it plays into ``feed_far``
just before playback, and the ``MicHub`` runs every mic frame through
``process``. When nothing is playing the far queue is empty and ``process`` is
a cheap passthrough.

The native dependency is optional (the ``aec`` extra; needs libspeexdsp-dev at
build time). ``build_aec`` degrades to ``None`` — a passthrough mic — when the
import fails, so the daemon never requires it to boot.
"""

from __future__ import annotations

import logging
import threading
from collections import deque

import numpy as np

log = logging.getLogger(__name__)


class SpeexEchoCanceller:
    """Frame-based echo canceller around ``speexdsp.EchoCanceller``.

    Speex wants short aligned frames (10-20 ms), so a mic block is split into
    ``frame_ms`` subframes, each cancelled against one queued far-end chunk.
    Alignment within the echo tail (``filter_length_ms``) is absorbed by the
    adaptive filter; ``extra_delay_ms`` coarsely compensates the output-path
    latency by pushing silence ahead of each clip's reference.
    """

    def __init__(
        self,
        sample_rate: int = 16000,
        frame_ms: int = 20,
        filter_length_ms: int = 200,
        extra_delay_ms: int = 0,
        echo_state=None,
    ) -> None:
        self._rate = sample_rate
        self._frame_samples = sample_rate * frame_ms // 1000
        self._frame_bytes = self._frame_samples * 2  # int16
        self._delay_chunks = max(0, extra_delay_ms // frame_ms)
        if echo_state is None:  # injectable for tests; lazy import of the native lib
            from speexdsp import EchoCanceller

            echo_state = EchoCanceller.create(
                self._frame_samples,
                sample_rate * filter_length_ms // 1000,
                sample_rate,
            )
        self._state = echo_state
        # 20 ms far-end chunks at the mic rate. Fed from the playback thread
        # (SoundDeviceOut._play runs in a worker), consumed on the event loop
        # (the MicHub pump), hence the lock.
        self._far: deque[bytes] = deque()
        self._lock = threading.Lock()

    @property
    def buffered_chunks(self) -> int:
        return len(self._far)

    def feed_far(self, pcm: bytes, rate: int) -> None:
        """Queue playback audio as the echo reference, resampled to the mic rate.
        Called with exactly what is about to reach the speaker."""
        samples = np.frombuffer(pcm, dtype=np.int16)
        if rate != self._rate:
            n_out = int(len(samples) * self._rate / rate)
            positions = np.linspace(0, len(samples) - 1, n_out)
            samples = np.interp(
                positions, np.arange(len(samples)), samples.astype(np.float32)
            ).astype(np.int16)
        data = samples.tobytes()
        silence = bytes(self._frame_bytes)
        with self._lock:
            if not self._far:
                # Clip start: delay the reference so it lines up with when the
                # echo actually arrives at the mic (output-device latency).
                self._far.extend(silence for _ in range(self._delay_chunks))
            for i in range(0, len(data), self._frame_bytes):
                chunk = data[i : i + self._frame_bytes]
                if len(chunk) < self._frame_bytes:
                    chunk += bytes(self._frame_bytes - len(chunk))
                self._far.append(chunk)

    def clear_far(self) -> None:
        """Drop the queued reference (playback was stopped)."""
        with self._lock:
            self._far.clear()

    def process(self, near: bytes) -> bytes:
        """Echo-cancel one mic block. Passthrough when nothing is playing."""
        with self._lock:
            if not self._far:
                return near
            out = bytearray()
            silence = bytes(self._frame_bytes)
            whole = len(near) - len(near) % self._frame_bytes
            for i in range(0, whole, self._frame_bytes):
                far = self._far.popleft() if self._far else silence
                out += self._state.process(near[i : i + self._frame_bytes], far)
            out += near[whole:]  # partial tail (never happens with fixed device blocks)
            return bytes(out)


def build_aec(
    sample_rate: int = 16000,
    frame_ms: int = 20,
    filter_length_ms: int = 200,
    extra_delay_ms: int = 0,
) -> SpeexEchoCanceller | None:
    """Construct the canceller, or return None (passthrough mic) when the
    optional native dependency isn't installed."""
    try:
        return SpeexEchoCanceller(
            sample_rate=sample_rate,
            frame_ms=frame_ms,
            filter_length_ms=filter_length_ms,
            extra_delay_ms=extra_delay_ms,
        )
    except Exception as exc:  # noqa: BLE001 - AEC is an optional enhancement, never fatal
        log.warning(
            "Echo cancellation unavailable (%s); mic passes through unprocessed. "
            'Install it with: sudo apt install libspeexdsp-dev && pip install -e ".[aec]"',
            exc,
        )
        return None
