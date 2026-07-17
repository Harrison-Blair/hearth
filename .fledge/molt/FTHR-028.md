# Molt evidence — FTHR-028: Audio surface spine (duplex capture loop and stage seams)

All spine tests use **stage doubles** and the **supplied-frames source** — no real
wake/VAD/STT and no hardware. A green suite here proves the spine **orchestrates a
turn and is duplex-shaped** (capture is continuous and turn-independent); it does
**not** prove any real wake/VAD/STT works (FTHR-029/030/031) nor that a real
microphone captures while playing on the Pi (FTHR-033 manual smoke). AC-4 proves the
loop is *structurally* duplex; the *acoustic* reality of capturing-while-playing is
PLM-009 + hardware.

Test command (worktree — use the venv's python with `-m pytest` from the worktree
root, never `.venv/bin/pytest`, per the worktree/editable-install gotcha):

```
/home/penguin/source/hearth/.venv/bin/python -m pytest tests/test_audio_surface.py tests/test_audio_source.py
```

## AC-1

The six spec-named tests (plus the AC-2/AC-3 import-contract test and a
supplied-source ordering sanity) were written first and run against the unchanged
tree. **Verbatim pre-implementation failing run** — every test fails for the expected
reason: the `hearth.audio` package does not exist yet.

```
=================================== FAILURES ===================================
E       ModuleNotFoundError: No module named 'hearth.audio'
tests/test_audio_surface.py:25: ModuleNotFoundError
E       ModuleNotFoundError: No module named 'hearth.audio'
tests/test_audio_surface.py:71: ModuleNotFoundError
E       ModuleNotFoundError: No module named 'hearth.audio'
tests/test_audio_surface.py:123: ModuleNotFoundError
E       ModuleNotFoundError: No module named 'hearth.audio'
tests/test_audio_surface.py:165: ModuleNotFoundError
E       ModuleNotFoundError: No module named 'hearth.audio'
tests/test_audio_surface.py:219: ModuleNotFoundError
E       ModuleNotFoundError: No module named 'hearth.audio'
tests/test_audio_surface.py:238: ModuleNotFoundError
E       ModuleNotFoundError: No module named 'hearth.audio'
tests/test_audio_surface.py:272: ModuleNotFoundError
E       ModuleNotFoundError: No module named 'hearth.audio'
tests/test_audio_source.py:19: ModuleNotFoundError
E       ModuleNotFoundError: No module named 'hearth.audio'
tests/test_audio_source.py:37: ModuleNotFoundError
FAILED tests/test_audio_surface.py::test_supplied_audio_drives_a_turn_end_to_end
FAILED tests/test_audio_surface.py::test_capture_continues_while_a_turn_is_in_flight
FAILED tests/test_audio_surface.py::test_unreachable_engine_is_retried_with_backoff
FAILED tests/test_audio_surface.py::test_unreachable_engine_gives_up_after_bounded_attempts
FAILED tests/test_audio_surface.py::test_audio_config_loads_independently_and_carries_wake_schema
FAILED tests/test_audio_surface.py::test_surface_presents_via_safety_policy
FAILED tests/test_audio_surface.py::test_audio_reaches_engine_only_over_the_wire
FAILED tests/test_audio_source.py::test_input_device_acquired_non_exclusively
FAILED tests/test_audio_source.py::test_supplied_frames_source_yields_in_order
9 failed in 0.03s
```

**Verbatim post-implementation passing run** — all nine pass:

```
collecting ... collected 9 items

tests/test_audio_surface.py::test_supplied_audio_drives_a_turn_end_to_end PASSED [ 11%]
tests/test_audio_surface.py::test_capture_continues_while_a_turn_is_in_flight PASSED [ 22%]
tests/test_audio_surface.py::test_unreachable_engine_is_retried_with_backoff PASSED [ 33%]
tests/test_audio_surface.py::test_unreachable_engine_gives_up_after_bounded_attempts PASSED [ 44%]
tests/test_audio_surface.py::test_audio_config_loads_independently_and_carries_wake_schema PASSED [ 55%]
tests/test_audio_surface.py::test_surface_presents_via_safety_policy PASSED [ 66%]
tests/test_audio_surface.py::test_audio_reaches_engine_only_over_the_wire PASSED [ 77%]
tests/test_audio_source.py::test_input_device_acquired_non_exclusively PASSED [ 88%]
tests/test_audio_source.py::test_supplied_frames_source_yields_in_order PASSED [100%]

============================== 9 passed in 0.03s ===============================
```

## AC-2

`hearth-audio` runs as its own veneer process (`[project.scripts]
hearth-audio = "hearth.audio.surface:main"` in `pyproject.toml`) reaching the engine
only over the wire: `hearth/audio/surface.py` submits turns via
`hearth.veneers.base.send_turn(websocket, transcript, "audio")` (`make_submit`) and
declares surface identity `SURFACE = "audio"`. It holds no in-process reference to
engine internals — proven by `test_audio_reaches_engine_only_over_the_wire`, which
AST-scans every file under `hearth/audio/` and asserts none imports
`hearth.brain`/`hearth.loop`/`hearth.memory`/`hearth.gateway`, and that the only
`hearth` imports are `hearth.config` (shared facility) and `hearth.veneers.base`
(client contract).

```
tests/test_audio_surface.py::test_audio_reaches_engine_only_over_the_wire PASSED
```

## AC-3

Wake, endpointing, and transcription are consumed through **injected interfaces**
defined here: `hearth/audio/stages.py` holds the `WakeDetector`, `Endpointer`, and
`Transcriber` Protocols (plus trivial doubles). `AudioSurface.__init__` takes
`source`, `wake`, `endpointer`, `transcriber`, `submit`, `present` as constructor
injections — the spine runs against doubles with no real stage present.
`test_supplied_audio_drives_a_turn_end_to_end` drives the full spine on
`ScriptedWakeDetector` / `ScriptedEndpointer` / `FixedTranscriber`. FTHR-029/030/031
implement the Protocols in their own files and inject them without touching the
spine.

```
tests/test_audio_surface.py::test_supplied_audio_drives_a_turn_end_to_end PASSED
```

## AC-4

**The load-bearing duplex criterion.** Capture is a single always-running task
(`AudioSurface._capture_loop`) that consumes frames and feeds wake detection; a
completed utterance is enqueued (`self._utterances.put`) and a **separate**
`_submit_loop` task submits it — the capture task never awaits the engine call.

`test_capture_continues_while_a_turn_is_in_flight` injects a submit seam that
**blocks forever**, feeds more frames while blocked, and asserts a **second wake is
still detected** within a bounded 1.5 s `wait_for`. The test is deadlock-shaped: a
sequential (submit-inside-capture) implementation stalls on the first blocked submit
and never reaches the second wake, so it **times out** rather than mis-asserting.

Verified structurally — the test **fails when the behavior breaks**. Temporarily
rewriting the capture loop to `await self._submit(transcript)` inline (the wrong
sequential shape) makes exactly this test fail with a `TimeoutError`:

```
>                   raise TimeoutError from exc_val
E                   TimeoutError
/usr/lib/python3.14/asyncio/timeouts.py:115: TimeoutError
FAILED tests/test_audio_surface.py::test_capture_continues_while_a_turn_is_in_flight
1 failed in 1.53s
```

Restoring the duplex (queue + separate submit task) shape makes it pass again.

**Honesty note:** this proves the loop is *structurally* duplex — capture does not
stop while a turn is outstanding. It does **not** prove the *acoustic* reality of
capturing while playing (that is PLM-009 + FTHR-033 hardware smoke).

## AC-5

The live input device is acquired **non-exclusively**: `hearth/audio/source.py`
names the mode with the module constant `NON_EXCLUSIVE` (documented: PortAudio/ALSA
open shared by default; no exclusive host-API `extra_settings` is ever requested,
so the mic stays usable while playback runs — FC-15). `LiveAudioSource.acquisition_mode
= NON_EXCLUSIVE` and `_open_stream` threads `acquisition=self.acquisition_mode` to
the stream factory. `test_input_device_acquired_non_exclusively` injects a fake
factory and asserts it received `acquisition == NON_EXCLUSIVE` (no real device).

```
tests/test_audio_source.py::test_input_device_acquired_non_exclusively PASSED
```

## AC-6

The surface **retries with backoff** when the engine is unreachable rather than
exiting (`open_with_retry` in `surface.py`, wrapping `hearth.veneers.base.connect`
— the contract's connect seam — in an `AsyncExitStack` with exponential backoff),
and proceeds once reachable. This is the deliberate divergence from `chat`'s
fail-fast. `test_unreachable_engine_is_retried_with_backoff` asserts it retries past
two `EngineUnreachable` failures with growing delays `[0.5, 1.0]` then yields the
connection; `test_unreachable_engine_gives_up_after_bounded_attempts` asserts retry
is bounded (raises after `max_attempts`).

```
tests/test_audio_surface.py::test_unreachable_engine_is_retried_with_backoff PASSED
tests/test_audio_surface.py::test_unreachable_engine_gives_up_after_bounded_attempts PASSED
```

## AC-7

The audio surface loads only `config/audio.yaml`, via PLM-007's shared facility
(`resolve_config_path("audio")`) with the engine's config absent.
`AudioSettings` (`hearth/audio/config.py`) is a standalone `BaseSettings` that never
touches the engine `Settings`. `test_audio_config_loads_independently_and_carries_wake_schema`
points `CONFIG_DIR` at a temp dir containing **only** `audio.yaml` (asserts
`engine.yaml` does not exist) and loads successfully.

```
tests/test_audio_surface.py::test_audio_config_loads_independently_and_carries_wake_schema PASSED
```

## AC-8

The audio config defines the **wake-model list schema** — `WakeModel(path, threshold)`
in an ordered `wake_models: list[WakeModel]`, **per-model threshold, no global
threshold** (FC-3). It is defined **only** in `hearth/audio/config.py`, annotated as
shared surface: read by FTHR-029, written by FTHR-032. The test parses two entries
and asserts order and per-model thresholds `[("…vesta.onnx", 0.5), ("…second.onnx",
0.72)]`, and that no global `threshold` attribute exists on the settings.

```
tests/test_audio_surface.py::test_audio_config_loads_independently_and_carries_wake_schema PASSED
```

## AC-9

Heard transcript and engine answer are presented through the surface end of PLM-007's
shared safety policy: `render(message)` is whitelist-only — it reads only the
already-curated `text`/`label`/`message` fields the gateway lets cross the boundary
and never reaches for `query`/`arguments`/`observation`/`result`.
`test_surface_presents_via_safety_policy` feeds a `tool_activity` dict carrying
forbidden internal keys and asserts the rendered output contains the safe label but
none of `SECRET_QUERY`/`SECRET_ARGS`/`SECRET_OBS`/`SECRET_RESULT`; errors present
only the curated `.message`. No speech is produced (that is PLM-009) — the surface
only `print`s / calls the injected `present`.

```
tests/test_audio_surface.py::test_surface_presents_via_safety_policy PASSED
```

## AC-10

No real wake/VAD/STT implementation is added: `hearth/audio/stages.py` holds only
Protocol interfaces and trivial doubles; the runnable `main()` wires those doubles as
explicitly-commented placeholders (FTHR-029/030/031 replace them via the injection
seam). No change to `training/manifest.py` or docs. Files touched by this feather
(new unless noted):

```
hearth/audio/__init__.py, hearth/audio/surface.py, hearth/audio/source.py,
hearth/audio/stages.py, hearth/audio/config.py,
config/audio.yaml, config/defaults/audio.yaml,
tests/test_audio_surface.py, tests/test_audio_source.py,
pyproject.toml (added only the hearth-audio [project.scripts] entry),
.fledge/molt/FTHR-028.md
```

`git diff --stat` confirms `training/` and docs are untouched.

## AC-11

`ruff check .` is clean and the full existing suite passes (141 tests, including the
9 new spine tests):

```
141 passed in 1.12s
=== RUFF ===
All checks passed!
```

