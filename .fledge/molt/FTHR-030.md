# FTHR-030 molt evidence — Utterance endpointing: VAD trailing-silence and max-length cap

Plumage PLM-008 · FC-5. Brooder `fledge-brooder-emperor`.

**What a green suite proves, and what it does not (AC-8).** A green suite proves
the endpointing **policy** is correct: trailing-silence counting, that speech
resets a mid-utterance pause, the max-length cap fires independently of silence,
that all three knobs (aggressiveness / silence / max) drive behavior from config,
and that the **real** `webrtcvad` classifies correctly-sized frames with no model
download. It does **NOT** prove the chosen silence/aggressiveness values *feel*
right to a human mid-conversation — whether the endpoint lands where a real
speaker expects. That is a tuning judgment on the Pi, verified by FTHR-033's
manual smoke and adjustable by config. Green here means "the policy is correct,"
not "the timings are well-tuned for real speech."

Test command (run from the worktree root; NOT `.venv/bin/pytest`, which would
test main's code):

```
/home/penguin/source/hearth/.venv/bin/python -m pytest tests/test_audio_endpoint.py -q
```

---

## AC-1

The five tests were written first and run against unchanged code (no
`hearth/audio/endpoint.py`), observed FAILING for the expected reason, then made
to pass by the implementation.

### Failing — before implementation (no `endpoint.py`)

```
$ /home/penguin/source/hearth/.venv/bin/python -m pytest tests/test_audio_endpoint.py -q
==================================== ERRORS ====================================
________________ ERROR collecting tests/test_audio_endpoint.py _________________
ImportError while importing test module '.../tests/test_audio_endpoint.py'.
Traceback:
tests/test_audio_endpoint.py:29: in <module>
    from hearth.audio.endpoint import VadEndpointer
E   ModuleNotFoundError: No module named 'hearth.audio.endpoint'
=========================== short test summary info ============================
ERROR tests/test_audio_endpoint.py
!!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
1 error in 0.05s
```

All five tests import `VadEndpointer` at module load, so the whole module fails
collection until the endpointer exists — the AC-1 baseline. Each test's own
"fails before" reason (no state machine, no cap, hardcoded values, no VAD
integration) is subsumed by this: there is no implementation to exercise.

### Passing — after implementation

```
$ /home/penguin/source/hearth/.venv/bin/python -m pytest tests/test_audio_endpoint.py -q
.....                                                                    [100%]
5 passed, 1 warning in 0.03s
```

(The one warning is `webrtcvad`'s own `pkg_resources` deprecation notice — the
reason the `vad` extra pins `setuptools<81`; not introduced by this feather.)

### Test-verification (mutation) — the tests fail when the behavior breaks

Per the repo's test-verification rule, the behavioral tests were confirmed to
fail on a broken implementation, not only to pass on the correct one:

```
# max-length cap removed:
FAILED test_max_length_cap_terminates_when_silence_never_arrives
FAILED test_config_drives_all_three_knobs               # (its cap assertions)
2 failed, 3 passed

# silence-run reset on speech removed:
FAILED test_max_length_cap_terminates_when_silence_never_arrives
FAILED test_config_drives_all_three_knobs
FAILED test_real_webrtcvad_classifies_frames
5 failed

# restored: 5 passed
```

---

## AC-2 — configurable trailing-silence; mid-utterance pauses do not end the turn

`test_utterance_ends_after_trailing_silence` proves the turn ends after *exactly*
the configured `silence_ms` (90 ms == 3 frames): it asserts `accept` returns
`None` after only 2 silence frames (60 ms) and ends on the 3rd
(`ended_reason == "silence"`), with the captured prefix containing all the
speech. `test_speech_resets_the_silence_run` proves a 60 ms mid-utterance pause
(< 90 ms) followed by more speech does **not** end the turn — only the final
continuous 90 ms run does. Both pass (see AC-1 passing run). Satisfies FC-5
(silence path).

## AC-3 — configurable max-length cap, fired independently of the silence path

`test_max_length_cap_terminates_when_silence_never_arrives` feeds a stream of
continuous speech (silence never accumulates) with `max_utterance_ms=150`
(== 5 frames) and asserts the turn is terminated at frame 5 with
`ended_reason == "max_length"` — a **distinct** termination reason from silence.
The mutation run above shows removing the cap makes exactly this test fail,
proving the cap is the thing under test. Satisfies FC-5 (the bound).

## AC-4 — real `webrtcvad` classifies frames, hermetic, no download

`test_real_webrtcvad_classifies_frames` constructs a `VadEndpointer` with **no**
injected classifier, so it builds a real `webrtcvad.Vad(aggressiveness)`. A loud
220 Hz tone is classified speech on every frame (utterance does not end); pure
silence is classified non-speech from the first frame and ends the turn at the
90 ms threshold. `webrtcvad` is a native extension with no model download, so the
test is hermetic. Frames are 30 ms mono int16 @ 16 kHz (960 bytes) — a valid
`webrtcvad` frame size. Satisfies FC-5's speech-detection basis.

## AC-5 — all three knobs read from config, no hardcoded timings

`test_config_drives_all_three_knobs` proves each knob drives behavior from
`EndpointConfig`:
- **silence_ms**: 60 ms vs 120 ms configs end the same stream at frame 4 vs 6.
- **max_utterance_ms**: 60 ms vs 120 ms configs cap the same speech stream at
  frame 2 vs 4.
- **aggressiveness**: with the real VAD (no injected classifier), a borderline
  tone is heard as speech at `aggressiveness=0` (never ends by silence → `None`)
  but as non-speech at `aggressiveness=3` (ends by silence) — same stream, same
  silence/max, only the configured aggressiveness differs.

`endpoint.py` holds no magic timings: `silence_ms`, `max_utterance_ms`, and
`aggressiveness` are all read from the injected `config`; `_BYTES_PER_SAMPLE = 2`
is the int16 PCM sample width (a format constant, not a policy timing).

## AC-6 — reads endpoint config keys; makes only the authorized minimal schema addition

Per the orchestrator amendment (spec commit f6032ca) that fired AC-6's
schema-insufficiency escape hatch, this feather made the **minimal** addition to
`EndpointConfig` in `hearth/audio/config.py`: a single field
`aggressiveness: int = 2` (webrtcvad range 0–3). No other class or config
section in that file was touched (siblings FTHR-031/FTHR-035 edit `STTConfig` /
the speaking config), and the file was not restructured. `silence_ms` and
`max_utterance_ms` are read as-is. Diff stays disjoint from FTHR-032.

## AC-7 — implements the `Endpointer` seam as given; no edit to `surface.py`/`stages.py`

`VadEndpointer` implements FTHR-028's frozen `Endpointer` Protocol exactly
(`accept(frame) -> bool`, `reset() -> None`); the method shapes match and the
surface's capture loop drives it unchanged. Neither `surface.py` nor `stages.py`
was modified (see the commit's file list). The `ended_reason` attribute is
additive and does not change the Protocol's method signatures.

Two seam observations were raised to the orchestrator rather than papered over:
(1) the missing aggressiveness config key (resolved by the amendment above), and
(2) `LiveAudioSource` uses `blocksize=512` (32 ms), which is **not** a valid
`webrtcvad` frame size (it accepts only 10/20/30 ms → 160/320/480 samples @ 16 kHz
and raises on 512) — a real-capture source-seam defect the orchestrator routed to
FTHR-033. This feather's tests use valid frame sizes accordingly.

## AC-8 — molt states green proves the policy, not the tuning

Stated at the top of this file: a green suite proves the endpointing **policy**
(silence counting, reset, cap) and that real `webrtcvad` classifies frames — it
does **not** prove the silence/aggressiveness values feel right to a human
mid-conversation, which is FTHR-033 manual smoke / Pi tuning, adjustable by
config.

## AC-9 — only the permitted files changed; `setuptools<81` pin undisturbed

Changed files: `hearth/audio/endpoint.py` (new), `tests/test_audio_endpoint.py`
(new), and the minimal `EndpointConfig.aggressiveness` addition in
`hearth/audio/config.py`. **No** `pyproject.toml` change was needed —
`webrtcvad` is already declared in the `vad` extra and is imported lazily (like
`source.py`'s `sounddevice`), so no new dependency edge exists. The `vad` extra's
`setuptools<81` pin is untouched. Disjoint from FTHR-029/031/032.

## AC-10 — ruff clean, full suite passes

```
$ /home/penguin/source/hearth/.venv/bin/ruff check .
All checks passed!

$ /home/penguin/source/hearth/.venv/bin/python -m pytest -q
146 passed, 1 warning in 1.15s
```
