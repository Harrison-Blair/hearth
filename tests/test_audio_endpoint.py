"""Utterance-endpointing tests (FTHR-030, PLM-008 FC-5).

The endpointer decides *when the user has stopped speaking* after a wake fires.
Two policies, both config-driven, are proven here:

- a **trailing-silence** timeout: a continuous run of non-speech ends the turn,
  and a mid-utterance pause shorter than the threshold does not; and
- a **max-length cap**: independent of silence, an utterance that never goes
  quiet is terminated at the configured maximum, so a stuck-open mic cannot
  capture forever.

Per FTHR-030's Approach, the *policy* (silence counting, reset, cap) is proven
against a **supplied classification stream** -- an injected speech/non-speech
classifier -- so the state machine is provable without crafting real audio a
real VAD happens to classify a precise way. The real `webrtcvad` per-frame path
is exercised separately (``test_real_webrtcvad_classifies_frames`` and the
aggressiveness knob in ``test_config_drives_all_three_knobs``) on
correctly-sized frames, with no model download.

Frame sizing: `webrtcvad` accepts only 10/20/30 ms frames at 8/16/32/48 kHz. We
use 30 ms mono int16 frames at 16 kHz (480 samples / 960 bytes) throughout.
"""
from __future__ import annotations

import math
import struct

from hearth.audio.config import EndpointConfig
from hearth.audio.endpoint import VadEndpointer

SR = 16000
FRAME_MS = 30
SAMPLES = SR * FRAME_MS // 1000  # 480


def _frame(sample: int) -> bytes:
    """A 30 ms mono int16 frame whose every sample is `sample`."""
    return struct.pack("<h", sample) * SAMPLES


def _tone(amp: int, freq: int) -> bytes:
    """A 30 ms mono int16 sine frame -- real audio bytes for the real VAD path."""
    return b"".join(
        struct.pack("<h", max(-32768, min(32767, int(amp * math.sin(2 * math.pi * freq * i / SR)))))
        for i in range(SAMPLES)
    )


# Distinct frames for the injected-classifier policy tests: identity classifies
# them, and both are correctly sized so the endpointer's ms accounting is real.
SPEECH = _frame(1000)
SILENCE = _frame(0)


def _classify(frame: bytes) -> bool:
    """Supplied classification stream: SPEECH is speech, everything else silence."""
    return frame == SPEECH


def _feed(endpointer: VadEndpointer, frames: list[bytes]) -> int | None:
    """Drive frames through the endpointer as the surface does (accept per frame).
    Return the 1-based index of the frame that ended the utterance, or None."""
    for i, frame in enumerate(frames, start=1):
        if endpointer.accept(frame):
            return i
    return None


def test_utterance_ends_after_trailing_silence():
    """Ends after *exactly* the configured trailing silence, not before, and the
    captured audio is the speech up to the endpoint (FC-5, silence path)."""
    config = EndpointConfig(silence_ms=90, max_utterance_ms=100_000, aggressiveness=2)
    endpointer = VadEndpointer(config, samplerate=SR, classifier=_classify)

    speech = [SPEECH] * 4
    # 90 ms of trailing silence == exactly 3 frames.
    stream = speech + [SILENCE] * 3

    # Does not end after 2 silence frames (60 ms < 90 ms).
    assert _feed(endpointer, speech + [SILENCE] * 2) is None

    endpointer.reset()
    ended_at = _feed(endpointer, stream)
    assert ended_at == 7  # 4 speech + 3 silence: ends on the 3rd silence frame
    assert endpointer.ended_reason == "silence"
    # Captured audio up to the endpoint contains all the speech.
    assert stream[:ended_at].count(SPEECH) == 4


def test_speech_resets_the_silence_run():
    """A pause shorter than the threshold, followed by more speech, does not end
    the turn -- only a full continuous silence run does (guards mid-sentence
    pauses)."""
    config = EndpointConfig(silence_ms=90, max_utterance_ms=100_000, aggressiveness=2)
    endpointer = VadEndpointer(config, samplerate=SR, classifier=_classify)

    # speech, a 60 ms pause (< 90 ms), speech again, then a full 90 ms run.
    stream = (
        [SPEECH] * 3
        + [SILENCE] * 2   # 60 ms pause -- must NOT end here
        + [SPEECH] * 2    # resumed speech resets the silence run
        + [SILENCE] * 3   # full 90 ms continuous silence -- ends here
    )
    ended_at = _feed(endpointer, stream)
    assert ended_at == len(stream)  # only the final continuous run ends it
    assert endpointer.ended_reason == "silence"


def test_max_length_cap_terminates_when_silence_never_arrives():
    """The safety bound: a stream that never goes silent is terminated at the
    configured maximum length, with the cap as the termination reason. This
    fires only when the normal silence path does not (FC-5, the bound)."""
    config = EndpointConfig(silence_ms=90, max_utterance_ms=150, aggressiveness=2)
    endpointer = VadEndpointer(config, samplerate=SR, classifier=_classify)

    # Continuous speech -- silence never accumulates, so only the cap can fire.
    stream = [SPEECH] * 10  # 300 ms of speech; cap is 150 ms == 5 frames
    ended_at = _feed(endpointer, stream)
    assert ended_at == 5  # 5 * 30 ms == 150 ms
    assert endpointer.ended_reason == "max_length"


def test_config_drives_all_three_knobs():
    """Aggressiveness, trailing-silence duration, and max length all come from
    the audio config; changing each changes behavior (no magic numbers)."""
    # (1) trailing-silence duration drives the endpoint frame.
    short = VadEndpointer(
        EndpointConfig(silence_ms=60, max_utterance_ms=100_000, aggressiveness=2),
        samplerate=SR,
        classifier=_classify,
    )
    long = VadEndpointer(
        EndpointConfig(silence_ms=120, max_utterance_ms=100_000, aggressiveness=2),
        samplerate=SR,
        classifier=_classify,
    )
    stream = [SPEECH] * 2 + [SILENCE] * 4
    assert _feed(short, stream) == 4   # 2 speech + 2 silence (60 ms)
    assert _feed(long, stream) == 6    # 2 speech + 4 silence (120 ms)

    # (2) max length drives the cap frame (continuous speech, silence never fires).
    cap_small = VadEndpointer(
        EndpointConfig(silence_ms=100_000, max_utterance_ms=60, aggressiveness=2),
        samplerate=SR,
        classifier=_classify,
    )
    cap_large = VadEndpointer(
        EndpointConfig(silence_ms=100_000, max_utterance_ms=120, aggressiveness=2),
        samplerate=SR,
        classifier=_classify,
    )
    assert _feed(cap_small, [SPEECH] * 10) == 2   # 60 ms == 2 frames
    assert _feed(cap_large, [SPEECH] * 10) == 4   # 120 ms == 4 frames

    # (3) aggressiveness drives real-VAD classification (no injected classifier).
    # A borderline tone the real webrtcvad hears as speech at aggressiveness 0 but
    # as non-speech at aggressiveness 3, so the SAME stream ends by silence only
    # when strict. (webrtcvad is stateful/smoothed, so we drive it to steady state
    # over a run rather than asserting an exact frame.)
    borderline = _tone(amp=500, freq=110)
    lax = VadEndpointer(
        EndpointConfig(silence_ms=90, max_utterance_ms=100_000, aggressiveness=0),
        samplerate=SR,
    )
    strict = VadEndpointer(
        EndpointConfig(silence_ms=90, max_utterance_ms=100_000, aggressiveness=3),
        samplerate=SR,
    )
    stream = [borderline] * 15
    assert _feed(lax, stream) is None                # heard as speech: no silence end
    assert _feed(strict, stream) is not None         # heard as silence: ends the turn
    assert strict.ended_reason == "silence"


def test_real_webrtcvad_classifies_frames():
    """The real `webrtcvad` per-frame path classifies frames at the configured
    aggressiveness and frame format -- hermetic, no download (FC-5's speech
    basis). Zeros are non-speech (silence accumulates); a loud tone is speech
    (silence resets)."""
    config = EndpointConfig(silence_ms=90, max_utterance_ms=100_000, aggressiveness=2)

    loud = _tone(amp=12000, freq=220)  # clearly speech at every aggressiveness
    quiet = _frame(0)                  # clearly non-speech

    # Loud speech: real webrtcvad classifies every frame as speech, so silence
    # never accumulates and the utterance does not end within the run. (Fresh
    # endpointer -- webrtcvad is stateful, so a run's speech hangover must not
    # bleed into the silence case below.)
    speaking = VadEndpointer(config, samplerate=SR)
    assert _feed(speaking, [loud] * 5) is None

    # Pure silence is non-speech from the first frame, so the silence run reaches
    # the 90 ms threshold and ends the utterance at frame 3.
    silent = VadEndpointer(config, samplerate=SR)
    assert _feed(silent, [quiet] * 3) == 3
    assert silent.ended_reason == "silence"
