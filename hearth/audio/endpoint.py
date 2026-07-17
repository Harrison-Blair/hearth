"""Utterance endpointing: the real `Endpointer` behind FTHR-028's seam (FC-5).

After a wake fires the surface feeds captured frames here one at a time and asks,
per frame, whether the utterance is complete (`accept`). The policy is a
**trailing-silence timeout bounded by a max-length cap**:

- speech/non-speech per frame comes from `webrtcvad` at the configured
  aggressiveness (the `vad` extra -- a small native lib, no model download); and
- the **decision on top of it** is this module's substance: a continuous run of
  non-speech reaching `silence_ms` ends the turn (speech resets the run), and
  independently, an utterance reaching `max_utterance_ms` is terminated so a
  stuck-open or noisy mic cannot capture forever.

All three knobs -- `aggressiveness`, `silence_ms`, `max_utterance_ms` -- come from
FTHR-028's `EndpointConfig` (`hearth.audio.config`); there are no magic timings
here. The per-frame classifier is injectable so the state machine is provable
against a supplied classification stream, but it defaults to the real
`webrtcvad`, which is also exercised directly (FTHR-030 Approach 5).

`webrtcvad` accepts only 10/20/30 ms frames at 8/16/32/48 kHz; the frame's
duration is derived from its byte length and the sample rate, so silence and cap
accounting is in real milliseconds regardless of frame size.
"""
from __future__ import annotations

from typing import Callable

# int16 mono PCM: two bytes per sample. The source (FTHR-028) captures mono int16.
_BYTES_PER_SAMPLE = 2


class VadEndpointer:
    """FTHR-028's `Endpointer` seam: `accept(frame) -> bool`, `reset()`.

    Reports the utterance complete when a continuous non-speech run reaches
    `silence_ms`, or when total captured audio reaches `max_utterance_ms`
    (whichever comes first). After a completing `accept`, `ended_reason` is
    `"silence"` or `"max_length"` -- the cap is a distinct termination reason
    from trailing silence.
    """

    def __init__(
        self,
        config,
        *,
        samplerate: int = 16000,
        classifier: Callable[[bytes], bool] | None = None,
    ) -> None:
        self._silence_ms = config.silence_ms
        self._max_utterance_ms = config.max_utterance_ms
        self._samplerate = samplerate
        self._classify = classifier if classifier is not None else self._build_vad(config.aggressiveness)
        self.reset()

    def _build_vad(self, aggressiveness: int) -> Callable[[bytes], bool]:
        """The real per-frame path: `webrtcvad` at the configured aggressiveness.
        Imported lazily so importing this module never requires the native lib
        (mirrors how the source lazy-imports `sounddevice`)."""
        import webrtcvad  # noqa: PLC0415 -- lazy: the `vad` extra is not needed to import

        vad = webrtcvad.Vad(aggressiveness)
        return lambda frame: vad.is_speech(frame, self._samplerate)

    def reset(self) -> None:
        """Start a fresh utterance: clear the silence run, elapsed length, and
        the recorded termination reason. Called at the start of each utterance."""
        self._silence_run_ms = 0
        self._elapsed_ms = 0
        self.ended_reason: str | None = None

    def accept(self, frame) -> bool:
        """Consume one utterance frame; return True when the utterance is complete."""
        duration_ms = self._frame_ms(frame)
        self._elapsed_ms += duration_ms

        if self._classify(frame):
            self._silence_run_ms = 0
        else:
            self._silence_run_ms += duration_ms

        # Trailing-silence timeout: the normal end of a turn.
        if self._silence_run_ms >= self._silence_ms:
            self.ended_reason = "silence"
            return True
        # Max-length cap: the safety bound when silence never arrives.
        if self._elapsed_ms >= self._max_utterance_ms:
            self.ended_reason = "max_length"
            return True
        return False

    def _frame_ms(self, frame) -> int:
        """Milliseconds of audio in `frame`, from its int16-mono byte length."""
        samples = len(frame) // _BYTES_PER_SAMPLE
        return samples * 1000 // self._samplerate
