# FTHR-031 — Offline transcription via faster-whisper — molt evidence

**What a green run here proves, and what it does NOT (decomposition Q4=A / AC-4).**
Every test mocks at the faster-whisper library boundary (`faster_whisper.WhisperModel`);
no real model is constructed and nothing is downloaded. A green suite proves the
**wiring** — the configured model / `compute_type` / `beam_size` / `language` reach
faster-whisper, and the returned transcript flows onward for submission as the turn.
It does **NOT** prove faster-whisper transcribes audio correctly: no real model runs in
CI, by the user's decision. Real supplied-audio-to-expected-text is FTHR-033's manual
smoke. This evidence records green as *"config reaches the library and the transcript
flows,"* never as *"transcription works."*

Test command (run from the worktree root):

```
/home/penguin/source/hearth/.venv/bin/python -m pytest tests/test_audio_transcribe.py -q
```

---

## AC-1

The four tests were written first and run against the unchanged code (no
`hearth/audio/transcribe.py`, and `STTConfig` still lacking `compute_type`/`beam_size`).
All fail at collection because the module does not exist — the expected fail-first
reason.

### Pre-implementation run (FAILING)

```
==================================== ERRORS ====================================
_______________ ERROR collecting tests/test_audio_transcribe.py ________________
ImportError while importing test module '/tmp/claude-1000/-home-penguin-source-hearth/69bd3e55-6685-474d-a6a3-120622bc7c54/scratchpad/FTHR-031/tests/test_audio_transcribe.py'.
Hint: make sure your test modules/packages have valid Python names.
Traceback:
/usr/lib/python3.14/importlib/__init__.py:88: in import_module
    return _bootstrap._gcd_import(name[level:], package, level)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
tests/test_audio_transcribe.py:23: in <module>
    from hearth.audio.transcribe import WhisperTranscriber
E   ModuleNotFoundError: No module named 'hearth.audio.transcribe'
=========================== short test summary info ============================
ERROR tests/test_audio_transcribe.py
!!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
1 error in 0.09s
```

### Post-implementation run (PASSING)

After adding `hearth/audio/transcribe.py` (`WhisperTranscriber`) and the authorized
`STTConfig` addition:

```
....                                                                     [100%]
4 passed in 0.12s
```

The two guard tests (`test_no_real_model_loads_in_ci` / AC-5,
`test_no_model_lifecycle_management` / AC-6) are marked so their fail-first is a
deliberate-violation demonstration, not the natural no-module error. Both were shown
failing when the guarded property was violated, then passing unmodified after restore —
see AC-5 and AC-6 below.

## AC-2 — configured model + params reach faster-whisper (FC-6)

`test_configured_model_params_reach_faster_whisper` patches
`faster_whisper.WhisperModel` and asserts, for two configs:

- default `STTConfig()` → constructor gets `("Systran/faster-distil-whisper-medium.en",
  compute_type="int8")`; `.transcribe(...)` gets `beam_size=5, language="en"` — the
  stenographer defaults reach the library.
- custom `STTConfig(model="tiny.en", compute_type="float16", beam_size=3, language="es")`
  → those exact custom values reach the constructor/call — proving the params are read
  from config, not hardcoded (a wrong config value would be caught here).

`hearth/audio/config.py::STTConfig` now carries all four as config with the stenographer
defaults; `WhisperTranscriber.__init__` builds the model from `config.model` /
`config.compute_type` and passes `config.beam_size` / `config.language` to
`.transcribe`. Passing (part of the `4 passed` run above).

## AC-3 — transcript flows onward for submission as the turn

`test_returned_transcript_flows_to_the_turn`: the faked model yields segments
`" Hello"`, `" there"`; `WhisperTranscriber.transcribe` returns `"Hello there"` (segment
texts joined, stripped). That returned string is exactly what the surface submits — the
surface's capture loop does `transcript = self._transcriber.transcribe(utterance)` then
enqueues it for submission (`hearth/audio/surface.py`), unchanged by this feather.
Passing.

## AC-4 — test-strategy boundary is explicit; wiring-proven, not accuracy-proven (Q4=A)

Stated in the test module docstring (`tests/test_audio_transcribe.py`) and at the top of
this evidence file: every test mocks at the faster-whisper boundary; a green run proves
config plumbing reaches the library and the transcript flows, and does **NOT** prove
transcription accuracy — that is FTHR-033's manual smoke. No test in this feather feeds
real audio or asserts recognised-vs-expected text; the model is always a `MagicMock`.

## AC-5 — no real model loads/downloads in CI; hermetic guard

`test_no_real_model_loads_in_ci` reloads the module under a patched
`faster_whisper.WhisperModel`, asserts `assert_not_called()` after import (no eager
construction), then asserts the only construction routed through the patched boundary.
faster-whisper is imported lazily inside `__init__`, so importing the module never loads
a model or downloads.

**Deliberate-violation demonstration** — adding an eager module-level
`faster_whisper.WhisperModel(...)` construction:

```
E           AssertionError: Expected 'WhisperModel' to not have been called. Called 1 times.
E           Calls: [call('Systran/faster-distil-whisper-medium.en', compute_type='int8')].
=========================== short test summary info ============================
FAILED tests/test_audio_transcribe.py::test_no_real_model_loads_in_ci
1 failed in 0.88s
```

Reverted → passes unmodified.

## AC-6 — no model-lifecycle policy; scope pin

`test_no_model_lifecycle_management`: the model is built once in `__init__`
(`WhisperModel.call_count == 1` immediately after construction) and reused across two
`transcribe` calls (still `== 1`), and the transcriber exposes none of
`load/unload/close/reload/shutdown/warm/evict`. `WhisperTranscriber` holds no lazy-load,
idle-unload or residency logic.

**Deliberate-violation demonstration** — deferring construction to first `transcribe`
(lazy load) plus an `unload()` method:

```
>           assert WhisperModel.call_count == 1
E           AssertionError: assert 0 == 1
E            +  where 0 = <MagicMock name='WhisperModel' ...>.call_count
=========================== short test summary info ============================
FAILED tests/test_audio_transcribe.py::test_no_model_lifecycle_management
1 failed in 0.14s
```

Reverted → passes unmodified.

## AC-7 — reads STT config; implements the seam as given

`transcribe.py` **reads** `STTConfig` and implements FTHR-028's `Transcriber` Protocol
(`stages.py`: `def transcribe(self, frames) -> str`) unchanged — `surface.py` and
`stages.py` are untouched. The one schema insufficiency (FC-6/AC-2 need `compute_type`
and `beam_size` as config, plus the correct `model` default, which FTHR-028's `STTConfig`
lacked) was raised as an escalation against FTHR-028; the orchestrator authorized (option
A) the minimal `STTConfig` addition recorded in the feather's amendment. No other config
section was touched (kept disjoint from FTHR-035's speaking config in the same file).

## AC-8 — diff scope (wave 2 disjoint)

`git diff --stat` + `git status`: only `hearth/audio/transcribe.py` (new),
`tests/test_audio_transcribe.py` (new), and the minimal `STTConfig` addition in
`hearth/audio/config.py` (6 insertions, 2 deletions, STTConfig only). **No `pyproject.toml`
change** — `faster-whisper` is already in the `stt` extra (FTHR-028), so no dependency
line was needed. Disjoint from FTHR-029/030/032.

## AC-9 — ruff clean, full suite green

```
$ ruff check .
All checks passed!

$ pytest -q
145 passed in 1.22s
```

## Note for review (not a code change here)

`config/defaults/audio.yaml` and `config/audio.yaml` still pin `stt.model: base` and omit
`compute_type`/`beam_size`. Because YAML overrides the schema default, the *active* config
resolves `model` to `base`, masking the new stenographer schema default at runtime
(`compute_type`/`beam_size` still resolve to `int8`/`5` from the schema since the YAML
omits them). Those YAML files are **outside this feather's authorized file whitelist**
(the amendment permits only `transcribe.py`, its test, and the `STTConfig` addition), and
the audio YAML is contested surface with FTHR-035, so I did not edit them. Flagging so the
orchestrator can decide whether a follow-up updates the shipped/reference YAML to the
stenographer defaults.

