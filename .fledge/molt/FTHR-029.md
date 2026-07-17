# Molt evidence — FTHR-029: Wake detection (multiple models, per-model thresholds)

Feather: `.fledge/pluma/feathers/FTHR-029-wake-detection-multiple-models-per-model-thresholds.md`
Branch: `feather/FTHR-029-wake-detection`

**Scope of a green suite (AC-7).** A green wake suite proves the *gating logic*
(which model fires at which threshold) and that the real committed `vesta.onnx`
*loads and scores* via livekit-wakeword/onnxruntime. It does **not** prove wake
**accuracy** on real speech — that a person saying the phrase reliably trips it
and ambient noise does not is a property of the trained model and real acoustics,
verified in **FTHR-033's manual smoke**, not here.

Test command (run from the worktree root, using the main venv's python so audio
deps are present — never `.venv/bin/pytest`, which would test main's install):

```
cd <worktree> && /home/penguin/source/hearth/.venv/bin/python -m pytest -q tests/test_audio_wake.py
```

## AC-1

The four tests named in the spec were written first and run against the
unchanged tree (no `hearth/audio/wake.py`). They fail at import for the expected
reason: the module under test does not yet exist.

```
$ /home/penguin/source/hearth/.venv/bin/python -m pytest -q tests/test_audio_wake.py
==================================== ERRORS ====================================
__________________ ERROR collecting tests/test_audio_wake.py ___________________
ImportError while importing test module '.../tests/test_audio_wake.py'.
Hint: make sure your test modules/packages have valid Python names.
Traceback:
/usr/lib/python3.14/importlib/__init__.py:88: in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
tests/test_audio_wake.py:26: in <module>
    from hearth.audio.wake import WakeDetector, WakeWordScorer
E   ModuleNotFoundError: No module named 'hearth.audio.wake'
=========================== short test summary info ============================
ERROR tests/test_audio_wake.py
!!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
1 error in 0.09s
```

Passing run after implementing `hearth/audio/wake.py`:

```
$ /home/penguin/source/hearth/.venv/bin/python -m pytest -q tests/test_audio_wake.py
......                                                                   [100%]
6 passed in 0.80s
```

The 6 = 3 standalone tests + the 3 parameterizations of
`test_detection_is_driven_by_the_configured_model_set`
(`three-synthetic`, `two-synthetic`, `one-real`).

**Test-verification (a test must fail when the behavior breaks).** With
`detect()` patched to gate on a single global (min) threshold — the FC-3
anti-pattern — the gating tests fail, and revert restores green:

```
FAILED tests/test_audio_wake.py::test_detection_is_driven_by_the_configured_model_set[three-synthetic]
FAILED tests/test_audio_wake.py::test_detection_is_driven_by_the_configured_model_set[two-synthetic]
FAILED tests/test_audio_wake.py::test_no_global_threshold_governs_detection
3 failed, 3 passed in 0.91s
```

(The single-model and real-load tests still pass — correctly, they don't
distinguish global vs. per-model; the three that do, fail.)

## AC-2

Active set is driven by the config's `wake_models` list.
`test_detection_is_driven_by_the_configured_model_set` is parameterized over a
three-model set, a two-model set, and the one-real-model set, running all three
through the **same** `_assert_each_gates_independently` harness. Multiple models
are active at once and any can fire; the one-model case works by the same code
path (`WakeDetector.detect` iterates `self._thresholds` with no length special
case). A hardcoded single-model detector cannot pass the multi-model
parameterizations (verified above: breaking the loop into a single global fails
the `three-synthetic`/`two-synthetic` cases).

## AC-3

Each model gates on its own threshold. `WakeDetector.__init__` builds
`{stem: threshold}` from each config entry; `detect` compares each model's score
against `self._thresholds[name]`. `test_no_global_threshold_governs_detection`
uses thresholds 0.4 and 0.9 (avg 0.65) with two assertions that together defeat
any single global value: `low@0.5` must fire (would not under a 0.65/0.9 global)
and `high@0.5` must not fire (would under a 0.4/avg global). Verified failing
against a global-threshold implementation above.

## AC-4

`test_real_vesta_model_loads_and_scores` constructs `WakeWordScorer([vesta.onnx])`
(real livekit-wakeword/onnxruntime load, no download — model is in-repo at
`models/wake/vesta.onnx`), feeds ~2.6 s of int16 silence frames, and asserts a
float score in `[0, 1]` under the key `"vesta"`. Confirmed the underlying path
returns `{'vesta': 0.0023...}` for a 2 s silence chunk. This proves load+score,
**not** accuracy (silence is not expected to cross the 0.77 threshold).

## AC-5

This feather only **reads** the wake-model schema: `wake.py` imports `WakeModel`
from `hearth.audio.config` and reads `.path`/`.threshold`. It defines no config
schema and does not touch `config.py`. `git status` shows only `wake.py`, the
test, and this molt file changed — no schema change, keeping it disjoint from
FTHR-032. (No schema insufficiency was found; had there been one it would be
raised against FTHR-028, not fixed here.)

## AC-6

`wake.py` implements FTHR-028's `WakeDetector` Protocol from `stages.py` as given
(`detect(self, frame) -> bool`) in a new file. `stages.py` and `surface.py` are
not modified (confirmed by `git status`). No seam problem was encountered.

## AC-7

Stated at the top of this file: a green suite proves the gating logic and that
`vesta.onnx` loads and scores; it does **not** prove wake accuracy on real speech
(FTHR-033 manual smoke). The `test_real_vesta_model_loads_and_scores` docstring
repeats this: "this proves load+score, not accuracy."

## AC-8

`git status --short` shows exactly:

```
?? .fledge/molt/FTHR-029.md
?? hearth/audio/wake.py
?? tests/test_audio_wake.py
```

Only `hearth/audio/wake.py` and `tests/test_audio_wake.py` are added (plus this
molt evidence). **`pyproject.toml` was not touched** — the `wake` extra's imports
(`livekit.wakeword`, `numpy`) are lazy inside `WakeWordScorer.__init__`, so no
new dependency edge was needed here (FTHR-028 owns `[project.scripts]`/deps).
Wave 2 stays disjoint from FTHR-030/031/032.

## AC-9

```
$ /home/penguin/source/hearth/.venv/bin/ruff check .
All checks passed!

$ /home/penguin/source/hearth/.venv/bin/python -m pytest -q
147 passed in 1.96s
```
