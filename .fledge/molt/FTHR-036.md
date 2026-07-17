# Molt evidence — FTHR-036: Text-to-speech rendering via piper

Concrete piper `Renderer` behind FTHR-035's `Renderer` seam (`hearth/audio/stages.py`),
mirroring FTHR-031's real-stage-behind-a-mocked-boundary layout (`hearth/audio/transcribe.py`).

- Implementation: `hearth/audio/render.py` (new) — `PiperRenderer`.
- Tests: `tests/test_audio_render.py` (new) — piper mocked at `piper.PiperVoice`.
- Boundary constant: no `pyproject.toml` change was needed (see AC-8).

**What CI proves here, and what it does not.** These hermetic tests prove the
*wiring* only: the configured `voice` reaches `piper.PiperVoice.load`, the answer
text reaches `synthesize`, and piper's returned audio becomes the frames the seam
hands the `Player`. They do **not** prove the speech is intelligible, natural, or
renders at usable latency on the Pi — that is real-audio quality, which no mock can
assert and which is deferred to **FTHR-039's manual smoke** on real hardware. A green
suite here is **"TTS wired correctly," not "TTS sounds right."** (This is FTHR-031's
Q4=A honesty transposed to the output side.)

## AC-1

The four tests were written first and run against the unchanged tree (no
`hearth/audio/render.py` exists). They fail at collection for the expected reason —
the renderer module does not exist yet.

```
$ cd <worktree> && /home/penguin/source/hearth/.venv/bin/python -m pytest -q tests/test_audio_render.py
==================================== ERRORS ====================================
_________________ ERROR collecting tests/test_audio_render.py __________________
ImportError while importing test module '.../tests/test_audio_render.py'.
Hint: make sure your test modules/packages have valid Python names.
Traceback:
/usr/lib/python3.14/importlib/__init__.py:88: in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
tests/test_audio_render.py:23: in <module>
    from hearth.audio.render import PiperRenderer
E   ModuleNotFoundError: No module named 'hearth.audio.render'
=========================== short test summary info ============================
ERROR tests/test_audio_render.py
!!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
1 error in 0.09s
```

Post-implementation, all four pass:

```
$ /home/penguin/source/hearth/.venv/bin/python -m pytest -v tests/test_audio_render.py
tests/test_audio_render.py::test_renderer_synthesises_configured_text_to_frames PASSED [ 25%]
tests/test_audio_render.py::test_configured_voice_and_params_reach_piper PASSED       [ 50%]
tests/test_audio_render.py::test_rendered_frames_satisfy_the_player_seam_contract PASSED [ 75%]
tests/test_audio_render.py::test_rendering_is_hermetic PASSED                          [100%]
============================== 4 passed in 0.07s ===============================
```

**Each test proven to fail when the behavior breaks** (test-verification rule):

- Hard-coding the loaded voice (`PiperVoice.load("HARDCODED")`) →
  `test_configured_voice_and_params_reach_piper` FAILS (`Actual: load('HARDCODED')`).
  The anti-hollow-mock test is real: config being ignored is caught.
- Returning piper's raw `audio_float_array` instead of `(sample_rate, samples)`
  frames → both `test_renderer_synthesises_configured_text_to_frames` and
  `test_rendered_frames_satisfy_the_player_seam_contract` FAIL (unpack error / wrong
  dtype). The frame-contract tests are real.

## AC-2

`PiperRenderer` (`hearth/audio/render.py`) **implements FTHR-035's `Renderer`
Protocol** (`stages.py::Renderer` — `render(self, text: str)`); it injects into that
seam and does not define a new one. `render` turns answer text into audio frames via
`piper.PiperVoice.synthesize` (PLM-009 FC-1, real-render half). Structurally a
`Renderer` — the Protocol is `@runtime_checkable`; `isinstance(PiperRenderer(...),
Renderer)` holds by the `render` method. Proven by
`test_renderer_synthesises_configured_text_to_frames`.

## AC-3

The configured `voice` reaches `piper.PiperVoice.load` and the answer text reaches
`synthesize`. `test_configured_voice_and_params_reach_piper` renders with two
distinct voices and asserts `load` is called with each — changing the configured
voice changes the piper call. Mutation check above (hard-coded voice) confirms the
test FAILS if config is ignored or the wiring is stubbed away. (There are no
additional synthesis-parameter config fields in `AudioSettings` — `voice` is the
configured input; inventing synthesis knobs would be out of scope.)

## AC-4

A rendered frame is a `(sample_rate, samples)` pair: a positive int rate and a mono
(`ndim == 1`) int16 `numpy` array — standard PCM the `Player` (FTHR-038) can open a
device on. `test_rendered_frames_satisfy_the_player_seam_contract` asserts this per
frame, so an inter-seam format disagreement fails here, not at FTHR-039's
composition. Mutation check above confirms the test FAILS on a wrong frame shape.

**Seam sufficiency note (no finding against FTHR-035).** FTHR-035's `Renderer`/
`Player` seam treats a frame as **opaque** — the surface routes render output to the
player untouched (`surface.py::_speak`), never inspecting it. piper voices carry a
model-specific sample rate, and the `Player` is a separate object with no reference
to the renderer, so the rate must travel **with** the frames. A self-describing
`(sample_rate, samples)` frame satisfies exactly this within the existing opaque-frame
seam — **no Protocol signature change is needed**, so this is adapting piper's output
to the contract (the adapter lives here), **not** routing around an insufficiency.
FTHR-035's seam is sufficient; no AC-7 finding was raised against it.

## AC-5

Rendering is **hermetic**: every piper construction routes through the patchable
`piper.PiperVoice` boundary (piper is imported lazily inside `__init__`, mirroring
`transcribe.py`), so CI triggers no voice-model download and touches no audio device.
`test_rendering_is_hermetic` reloads the module under the patch and asserts
`PiperVoice.assert_not_called()` (no eager load at import), then that the only
construction went through the patched boundary (PLM-009 FC-11, render stage). Mirrors
FTHR-031's `test_no_real_model_loads_in_ci` (Q4=A).

## AC-6

Scope: this feather contains **no device playback** (that is FTHR-038's `Player` —
`render` only returns frames, it never opens a device), **no voice acquisition or
first-run error** (that is FTHR-037 — `PiperRenderer` loads a voice that is present
and does not fetch or handle an absent one), and **no barge-in**. The `Renderer` seam
was found **sufficient** (see AC-4 note) — no seam insufficiency was worked around
here, and none needed raising against FTHR-035. Files touched: `hearth/audio/render.py`
(new) and `tests/test_audio_render.py` (new) only. `hearth/audio/surface.py` was
**not** touched (the surface startup/wiring path is FTHR-037's).

## AC-7

Recorded at the top of this file: CI proves **wiring, not audio quality/
intelligibility/latency**. A green suite here is **"TTS wired correctly," not "TTS
sounds right"** — real-audio properties remain a promissory note discharged only at
**FTHR-039's manual smoke** on hardware.

## AC-8

**No `pyproject.toml` change was needed.** piper is already declared as the `tts =
["piper-tts"]` extra and is importable in the runtime venv; the tests mock at
`piper.PiperVoice`, and the renderer imports piper lazily, so no dependency edit and
no widening of `all` was required. (`all` already includes `tts`.)

`ruff check .` is clean and the full existing suite passes:

```
$ /home/penguin/source/hearth/.venv/bin/python -m ruff check .
All checks passed!

$ /home/penguin/source/hearth/.venv/bin/python -m pytest -q
170 passed, 1 warning in 2.03s
```

(The one warning is the pre-existing `webrtcvad`/`pkg_resources` deprecation from
`test_audio_endpoint.py`, unrelated to this feather.)
