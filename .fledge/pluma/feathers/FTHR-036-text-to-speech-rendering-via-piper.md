---
id: FTHR-036
title: Text-to-speech rendering via piper
plumage: PLM-009
status: egg
priority: P1
depends_on: [FTHR-035]
authored: 2026-07-17T16:06:41Z
agent: fledge-orchestrate/planning
fledge_version: 0.6.8
---

# FTHR-036: Text-to-speech rendering via piper

## Description

Supplies the **real `Renderer`** — the concrete implementation of the text→audio seam FTHR-035
defined — backed by **piper** (`tts = ["piper-tts"]`, the extra that is declared and today consumed
by nothing). This is the speaking-side mirror of FTHR-031 (STT via faster-whisper): a real library
wired behind a seam the surface already knows, with the library **mocked at its boundary** so CI
proves the wiring hermetically and needs no audio hardware, no model, and no sound card.

The renderer takes the engine's final-answer text and the configured voice, and produces audio
frames the `Player` (FTHR-038) will consume. It **injects into FTHR-035's `Renderer` Protocol** — it
does not invent a seam. If that Protocol turns out to be the wrong shape for what piper needs
(e.g. it must return a sample rate alongside frames, or stream chunks), that insufficiency is a
**finding against FTHR-035** (its AC-7), corrected there, not routed around with a second seam here.

**What this feather proves, and what it does not.** Its hermetic tests prove piper is **invoked
with the configured voice and parameters and that its output becomes the frames the seam returns** —
the *wiring*. They do **not** prove the speech is intelligible, natural, or correct-sounding: that
is real-audio quality, which no mock can assert and which lands in **FTHR-039's manual smoke** on
real hardware. This is exactly FTHR-031's Q4=A honesty, transposed to output: mock the heavy
library at its edge, prove the plumbing, defer the acoustics to the smoke.

**Boundaries.** No device playback (that is FTHR-038's `Player`). No voice **acquisition** — this
feather **loads and renders with** a voice that is present; *fetching* it, and the first-run error
when it is absent, are FTHR-037 (disjoint file). No barge-in. This feather is one file's worth of
"turn text into frames with piper," and nothing more.

**Runs in wave 2, parallel with FTHR-037 (acquisition) and FTHR-038 (playback+barge-in)** — three
disjoint workers against FTHR-035's seams. Depends on **FTHR-035** (the `Renderer` seam and the
voice config key it renders from).

## Affected Modules

See `.fledge/nest/index.md`; `pyproject.toml` (the `tts = ["piper-tts"]` extra and its pin
comments — read them before touching deps); FTHR-035's `Renderer` seam and `voice` config key;
FTHR-031's faster-whisper renderer as the **boundary-mock pattern to mirror** (real library behind
a seam, mocked at its edge in tests).

- `hearth/audio/**` — the concrete piper `Renderer` implementing FTHR-035's Protocol. Match
  FTHR-035's seam signature and FTHR-031's real-stage layout/style exactly.
- `pyproject.toml` — only if the `tts` extra needs adjusting to actually import piper; read the pin
  comments first and note any change at the gate. Do not widen `all`'s contents beyond what exists.
- `tests/` — new test module mocking piper at its library boundary.

**Files this feather must NOT touch:** the `Player`/device path (FTHR-038), the voice-acquisition
path (FTHR-037), the seam *definition* (FTHR-035 owns it — implement it, don't redefine it), and
the listening input path (FTHR-029/030/031). The engine is not modified.

## Approach

**1. Implement the `Renderer` Protocol with piper.** Load the piper voice named in config (FTHR-035's
`voice` key) and synthesise the given text to audio frames. Keep the surface depending on the
Protocol; this concrete is injected exactly as FTHR-031's transcriber is.

**2. Mock piper at its library boundary (the FTHR-031 constraint holds here).** CI must not
download or load a real voice model or touch an audio device. Tests substitute the piper call at
its edge and assert **what the renderer asked piper to do** — the configured voice, the text, any
synthesis parameters — and that piper's returned audio is what the seam hands on. This mirrors
FTHR-031's Q4=A decision on the input side.

**3. Guard against a hollow mock.** A mock that is never meaningfully invoked would pass a naive
test while proving nothing (the FTHR-031 anti-hollow-mock lesson). At least one test must assert the
**configured voice and parameters actually reach the piper call** — change the configured voice, and
the call piper receives changes. So the test fails if the renderer ignores config and hard-codes,
or if the wiring is stubbed away.

**4. Frames match the seam contract.** Whatever shape FTHR-035's seam specifies for audio frames
(format/sample-rate expectations the `Player` will consume), the piper renderer must produce it. If
piper's native output must be adapted to that contract, the adapter lives here; if the *contract
itself* is underspecified for real audio, that is a finding against FTHR-035.

**Constraints.** Real piper behind FTHR-035's seam; mocked at the library edge in CI; no device, no
download, no acquisition, no barge-in. Respect `pyproject.toml`'s existing pins and comments. Match
existing style; surgical — only the renderer and its test.

## Tests

Test-first: (1) write; (2) run against the unchanged tree (no piper renderer exists — only
FTHR-035's double), confirm FAIL for the expected reason; (3) implement until green.

- `test_renderer_synthesises_configured_text_to_frames` (new) — the piper `Renderer` takes answer
  text and returns audio frames matching the seam contract, with piper mocked at its boundary.
  *Fails before:* no concrete renderer exists. FC-1 (the real-render half; the seam half was
  FTHR-035).
- `test_configured_voice_and_params_reach_piper` (new) — the **anti-hollow-mock** test: the voice
  named in config and the synthesis parameters are what the piper call receives; changing the
  configured voice changes the call. *Fails before:* no wiring / config not threaded to piper.
  Guards the mock from proving nothing.
- `test_rendered_frames_satisfy_the_player_seam_contract` (new) — the frames the renderer returns
  are well-formed for the `Player` seam (format/sample-rate as FTHR-035's contract specifies), so a
  format disagreement is caught here, not at FTHR-039's composition. *Fails before:* no renderer.
- `test_rendering_is_hermetic` (new) — rendering triggers **no** voice-model download and needs
  **no** audio device; piper is mocked at its edge. Guards the hermetic property against a later
  edit that reaches for a real model or device. *Fails before:* n/a until wired; a guard.

**What CI proves here, and what only the smoke can.** CI proves the **renderer invokes piper with
the configured voice/params and turns text into seam-correct frames** — hermetically. CI does
**not** prove the speech sounds right, is intelligible, or renders at usable latency on the Pi —
those are real-audio properties, provable only in **FTHR-039's manual smoke**. Molt evidence must
record the green wiring proof **and** state plainly that audio quality/intelligibility remains a
promissory note discharged only at FTHR-039. A green suite here is not "TTS works" — it is "TTS is
wired correctly."

## Acceptance Criteria

- [ ] AC-1: The tests listed above were observed failing before implementation and pass after.
- [ ] AC-2: A concrete piper-backed `Renderer` **implements FTHR-035's `Renderer` Protocol** (it
      injects into that seam; it does not define a new one) and turns answer text into audio frames
      (satisfies PLM-009 FC-1, real-render half).
- [ ] AC-3: The **configured voice and synthesis parameters reach the piper call** — an
      anti-hollow-mock test asserts changing the configured voice changes what piper is asked to do,
      so the test fails if config is ignored or the wiring is stubbed away.
- [ ] AC-4: The renderer's output frames satisfy FTHR-035's `Player`-seam contract
      (format/sample-rate), so an inter-seam format disagreement fails here rather than at FTHR-039's
      composition.
- [ ] AC-5: Rendering is **hermetic** — CI triggers no voice-model download and needs no audio
      device (piper mocked at its library boundary, mirroring FTHR-031's Q4=A); a test guards the
      property (satisfies PLM-009 FC-11 for the render stage).
- [ ] AC-6: This feather contains **no device playback** (FTHR-038), **no voice acquisition/first-run
      error** (FTHR-037), and **no barge-in**; any `Renderer`-seam insufficiency was raised as a
      finding against FTHR-035, not worked around here.
- [ ] AC-7: Molt evidence records that CI proves **wiring, not audio quality/intelligibility/
      latency** — those remain deferred to FTHR-039's manual smoke; a green suite here is "TTS wired
      correctly," not "TTS sounds right."
- [ ] AC-8: Any `pyproject.toml` dependency change is minimal, respects the existing pin comments,
      and is noted at the gate; `ruff check .` is clean and the full existing test suite passes.
