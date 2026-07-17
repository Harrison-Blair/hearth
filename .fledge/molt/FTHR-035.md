# Molt evidence — FTHR-035: Speaking surface extension (render/playback seams + tagged presentation)

**Honesty note.** This feather is pure scaffolding: correct seams, the call-site
rule, the presentation, and the config shape — **all with doubles, zero sound**.
Green here does NOT prove real speech (FTHR-036), the first-run absent-voice UX
(FTHR-037), real playback/barge-in (FTHR-038), or anything audible (FTHR-039 smoke).

Test command (from the worktree root):

```
/home/penguin/source/hearth/.venv/bin/python -m pytest tests/test_audio_speaking.py -q
```

## AC-1

The five speaking tests were written first and run against the unchanged surface
(which has no `Renderer`/`Player` seams, no speak call site, no `present_line`, and
no speaking config keys). All five FAIL for the expected reason.

### Pre-implementation run (FAIL — expected)

```
__________ test_final_answer_is_rendered_and_played_through_the_seams __________
E       ImportError: cannot import name 'MarkerRenderer' from 'hearth.audio.stages'
tests/test_audio_speaking.py:32: ImportError
________________ test_tool_activity_is_never_rendered_to_speech ________________
E       ImportError: cannot import name 'MarkerRenderer' from 'hearth.audio.stages'
tests/test_audio_speaking.py:77: ImportError
________ test_heard_and_spoken_presented_with_distinct_tags_and_colours ________
E       ImportError: cannot import name 'present_line' from 'hearth.audio.surface'
tests/test_audio_speaking.py:130: ImportError
___________ test_output_device_defaults_to_system_default_when_unset ___________
E       ImportError: cannot import name 'SYSTEM_DEFAULT' from 'hearth.audio.stages'
tests/test_audio_speaking.py:151: ImportError
________________ test_speaking_config_loads_via_shared_facility ________________
tests/test_audio_speaking.py:201:
E                   AttributeError: 'AudioSettings' object has no attribute 'voice'
=========================== short test summary info ============================
FAILED tests/test_audio_speaking.py::test_final_answer_is_rendered_and_played_through_the_seams
FAILED tests/test_audio_speaking.py::test_tool_activity_is_never_rendered_to_speech
FAILED tests/test_audio_speaking.py::test_heard_and_spoken_presented_with_distinct_tags_and_colours
FAILED tests/test_audio_speaking.py::test_output_device_defaults_to_system_default_when_unset
FAILED tests/test_audio_speaking.py::test_speaking_config_loads_via_shared_facility
5 failed in 0.04s
```

### Post-implementation run (PASS)

```
tests/test_audio_speaking.py::test_final_answer_is_rendered_and_played_through_the_seams PASSED [ 20%]
tests/test_audio_speaking.py::test_tool_activity_is_never_rendered_to_speech PASSED [ 40%]
tests/test_audio_speaking.py::test_heard_and_spoken_presented_with_distinct_tags_and_colours PASSED [ 60%]
tests/test_audio_speaking.py::test_output_device_defaults_to_system_default_when_unset PASSED [ 80%]
tests/test_audio_speaking.py::test_speaking_config_loads_via_shared_facility PASSED [100%]
============================== 5 passed in 0.02s ===============================
```

## AC-2 — output seams `Renderer`/`Player`, answer → render → play (FC-1, FC-11)

`hearth/audio/stages.py` adds `Renderer` (`render(text)->frames`) and `Player`
(`play(frames)`) as `runtime_checkable` Protocols **alongside** FTHR-028's
`WakeDetector`/`Endpointer`/`Transcriber`, with doubles `MarkerRenderer` (marker
frames + records rendered text) and `RecordingPlayer` (records played frames +
device target). `AudioSurface._speak` renders the final answer and plays the
frames. Proven by `test_final_answer_is_rendered_and_played_through_the_seams`:
`renderer.rendered == ["hello there"]` and `player.played == [rendered frames]` —
no audio hardware.

## AC-3 — only the final answer is spoken; tool activity never rendered (FC-8)

`AudioSurface._submit_loop` calls `_speak` **only** for `type == "answer"`
messages; tool-activity/error messages are presented via `render()` but never
handed to the renderer. Proven by `test_tool_activity_is_never_rendered_to_speech`:
a turn returning `tool_activity` + `answer` leaves `renderer.rendered == ["it is
noon"]` while the tool label still appears in the visual presentation.

## AC-4 — `[heard]`/`[spoken]` distinct tags and colours, pure function (FC-9)

`hearth/audio/surface.py::present_line(text, tag, colors)` is a pure
`(text, tag) -> styled line` producing `[<ansi>tag<reset>] text` in the surface
family's style. Proven by
`test_heard_and_spoken_presented_with_distinct_tags_and_colours`: distinct tags
(`heard`/`spoken`) and distinct ANSI colours (36 vs 35), no device.

## AC-5 — output device is config, defaults to system default (FC-5)

`AudioSettings.output_device: str | None = None` mirrors `input_device`.
`stages.resolve_output_device(None) == SYSTEM_DEFAULT`, else the configured
device. Proven by `test_output_device_defaults_to_system_default_when_unset`: with
no key the resolved player target is `SYSTEM_DEFAULT`; with `hw:CARD=Device` set it
is that device — proven at the config/seam boundary with the `RecordingPlayer`
double.

## AC-6 — voice/output-device/presentation in `config/audio.yaml`, voice has no default (FC-2/FC-12)

`AudioSettings` gains `voice: str | None = None` (no shipped default),
`output_device`, and `presentation: PresentationConfig`. `config/audio.yaml` and
`config/defaults/audio.yaml` extended (the one audio config file — no second
file). Proven by `test_speaking_config_loads_via_shared_facility`: the keys load
through the shared facility; an unset `voice` is `None` (absent), never a silent
fallback.

## AC-7 — extends FTHR-028's single surface and its one config file

All changes are additive to the existing `hearth/audio/` surface and the single
`config/audio.yaml`: output seams added *alongside* the input seams in
`stages.py`, config keys added to the existing `AudioSettings`. No second surface,
no second config file. The input Protocols' signatures are unchanged.

## AC-8 — no piper/TTS, no real device, no download, no barge-in; doubles only

The diff imports no TTS library and opens no device: `MarkerRenderer` returns
marker tuples, `RecordingPlayer` records. Only the two seams, three config keys
(`voice`/`output_device`/`presentation`), and the `present_line` function the
tests exercise were added — no speculative abstraction.

```
$ grep -rn -iE "import .*(piper|sounddevice|onnx)" hearth/audio/stages.py hearth/audio/surface.py hearth/audio/config.py
(no matches — the speaking additions import no TTS/device library; the lazy
 `import sounddevice` in source.py is FTHR-028's input side, untouched here)

$ grep -rn -iE "piper|barge|download" hearth/audio/stages.py
17: ... FTHR-036 supplies the real piper `Renderer` ...   # docstring reference only
```

## AC-9 — listening path untouched, engine unmodified, ruff clean, suite green

No edits to wake/endpoint/transcribe stage doubles' signatures, the source, or
the engine (`hearth/loop.py`, `hearth/brain/**`). `ruff check .` → `All checks
passed!`; full suite → `146 passed`.

