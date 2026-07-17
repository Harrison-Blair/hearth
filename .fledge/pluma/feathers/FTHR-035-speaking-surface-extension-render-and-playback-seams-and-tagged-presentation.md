---
id: FTHR-035
title: "Speaking surface extension: render and playback seams and tagged presentation"
plumage: PLM-009
status: egg
priority: P1
depends_on: [FTHR-028]
authored: 2026-07-17T16:04:23Z
agent: fledge-orchestrate/planning
fledge_version: 0.6.8
---

# FTHR-035: Speaking surface extension: render and playback seams and tagged presentation

## Description

The spine-extension hoist for the speaking half. This feather adds *speaking* to the **single
audio surface** FTHR-028 stood up — it does not build a second surface. Everything the two
parallel workers (FTHR-036 TTS, FTHR-038 playback+barge-in) and the acquisition worker (FTHR-037)
build against is defined here, once, so they collide on nothing. It is the speaking analogue of
FTHR-028: seams + config + presentation, all provable with doubles and no audio hardware.

Four things land here and nowhere else:

1. **The two output seams.** A `Renderer` (text → audio frames) and a `Player` (audio frames →
   output device), each a small Protocol on the audio surface, mirroring FTHR-028's
   `WakeDetector`/`Endpointer`/`Transcriber` input seams. FTHR-036 supplies the real piper
   `Renderer`; FTHR-038 supplies the real device `Player` and drives its lifecycle/interruption.
   This feather ships **doubles** for both and wires the surface to call them — text answer in,
   `Renderer` produces frames, `Player` consumes them.

2. **The speaking configuration**, in the audio surface's own `config/audio.yaml` (the file
   FTHR-028 created, loaded by the shared facility from FTHR-022). Three keys:
   - **voice**: **required, no shipped default** (FC-2). This feather defines the key and the
     no-default stance in the schema; the *first-run acquisition/error behaviour* is FTHR-037's.
     Here the schema simply has no default and the surface has a place to read the name from.
   - **output device**: optional, **defaulting to the system default device** (FC-5), mirroring how
     FTHR-028 configures the input device.
   - **presentation/tagging**: whatever the `[heard]`/`[spoken]` presentation below needs.

3. **The `[heard]`/`[spoken]` tagged, coloured presentation** (FC-9). The surface already prints
   the heard transcript and the engine's answer (FTHR-028/033, listening-side). This feather adds
   the **distinction**: what was *heard* and what was *spoken* are tagged and coloured differently
   so a conversation can be followed and debugged as it happens aloud. Presentation is a pure,
   testable function of (text, tag) → styled line — no device needed to prove it.

4. **The "only the final answer is spoken" rule** (FC-8). The surface renders the engine's **final
   answer** to the `Renderer` and **never** renders tool activity. This is a wiring rule at the
   speak call site — the same discipline the veneer's `protocol.py` whitelist enforces on the wire —
   and it is proven here with a double that records *what was handed to the renderer*, asserting
   tool-activity events never reach it.

**What this feather is NOT.** No piper, no real device, no voice download, no barge-in. Those are
FTHR-036/037/038. This is the seam-and-config foundation they build against — if a downstream
worker finds the seam or schema insufficient, that is a **finding against this feather**, not a
competing seam invented in their own file. That is exactly the constraint (FTHR-028 AC-8's shape)
that keeps wave 2 disjoint.

**Runs in wave 1 alone**; FTHR-036/037/038 run in wave 2 against what this defines. Depends on
**FTHR-028** at the feather level (it extends that surface and its config); PLM-009 as a whole
depends on the PLM-007 platform at the plumage level.

## Affected Modules

See `.fledge/nest/index.md` and `.fledge/nest/architecture.md` → the audio surface (FTHR-028);
`hearth/config.py` (the shared facility, FTHR-022); FTHR-028's `config/audio.yaml` and its input
seams, whose shape these output seams mirror.

- `hearth/audio/**` — the surface FTHR-028 created. Add the `Renderer` and `Player` Protocol
  seams (alongside the existing `WakeDetector`/`Endpointer`/`Transcriber`), the speak call site
  that renders the final answer and drives the player, and the `[heard]`/`[spoken]` presentation.
  Match FTHR-028's module layout and seam style exactly — do not restructure it.
- `config/audio.yaml` (+ its defaults under `config/defaults/`) — add the `voice` (required, no
  default), `output device` (default = system default), and presentation/tagging keys. Extend the
  config model FTHR-028 defined for this file; do not create a second config file.
- `tests/` — new test module(s) for the seams, the speak-call-site rule, and the presentation.

**Files this feather must NOT touch:** piper / any TTS library (FTHR-036), the voice-acquisition
path (FTHR-037), the real device player and barge-in lifecycle (FTHR-038), and anything on the
**listening** input path (FTHR-029/030/031 — endpoint/STT are untouched by speaking). The engine
(`hearth/loop.py`, `hearth/brain/**`) is not modified — speaking consumes the engine's existing
final-answer output; it does not change how answers are produced.

## Approach

**1. Define the seams as Protocols, doubles first.** `Renderer.render(text) -> audio frames` and
`Player.play(frames)` / lifecycle, as narrow as FTHR-028's input seams. Ship a fake renderer
(returns marker frames for given text) and a **recording** fake player (captures what it was told
to play) so the surface is fully exercised with no device. The real implementations are injected by
FTHR-036/038 exactly as FTHR-028 injects real wake/endpoint/STT — the surface depends on the
Protocol, never the concrete.

**2. Wire the speak call site to the engine's final answer only.** When a turn completes, the
surface hands the **final answer** text to the `Renderer` and the frames to the `Player`. Tool
activity (the consult/ReAct intermediate events) is **never** handed to the renderer. Prove it with
the recording renderer double: drive a turn that involves tool activity and assert the renderer saw
the final answer and *only* that — the FC-8 guarantee, tested where it is enforced.

**3. Presentation is a pure function.** `(text, tag) -> styled line`, tag ∈ {heard, spoken}, each
with its own colour, reusing whatever styling the listening surface already uses for its printed
output (match it, don't reinvent). Test it directly on strings — distinct tags, distinct colours,
no device.

**4. Config: define the keys, defer the behaviours.** Add `voice` with **no default** so an unset
voice is representable as "missing" (FTHR-037 turns that into the first-run error); `output device`
defaulting to the system default (FC-5); presentation/tagging knobs. This feather proves the keys
**load** via the shared facility into the surface's config; it does **not** implement the
absent-voice error (FTHR-037) or real device selection (FTHR-038).

**Constraints.** Extend FTHR-028's surface and its one config file; define seams once here; no
piper, no device, no download, no barge-in. Everything provable with doubles — CI needs no audio
hardware. Match existing style; touch only the speaking additions (surgical — the listening path is
not refactored).

## Tests

Test-first: (1) write; (2) run against the unchanged surface (which has no speaking seams,
speak-call-site, or presentation), confirm FAIL for the expected reason; (3) implement until green.

- `test_final_answer_is_rendered_and_played_through_the_seams` (new) — a turn's final answer is
  handed to the injected `Renderer` and the produced frames to the injected `Player`, both doubles.
  *Fails before:* no seams / no speak call site exists. The FC-1 seam proof (real render/play are
  FTHR-036/038).
- `test_tool_activity_is_never_rendered_to_speech` (new) — drive a turn that produces tool activity
  plus a final answer; the recording renderer double saw the final answer and **not** the tool
  activity. *Fails before:* speak call site does not exist / would speak everything. The FC-8
  guarantee, tested at the call site that enforces it.
- `test_heard_and_spoken_presented_with_distinct_tags_and_colours` (new) — the presentation
  function renders a heard line and a spoken line with different tags and different colours.
  *Fails before:* no `[spoken]` tag/colour distinction exists (listening only ever printed heard +
  answer undifferentiated). FC-9.
- `test_output_device_defaults_to_system_default_when_unset` (new) — with no output device
  configured, the surface's resolved player target is the system default; with one set, it is that
  device. Proven at the config/seam boundary with a double (real device selection is FTHR-038).
  *Fails before:* no output-device key. FC-5.
- `test_speaking_config_loads_via_shared_facility` (new) — `voice`, output device, and tagging keys
  load from `config/audio.yaml` through the shared facility into the surface's config; `voice` has
  **no default** (unset ⇒ absent, not a silent fallback). *Fails before:* keys not in the schema.
  FC-12, and the FC-2 no-default stance at the schema level.

**What a green suite proves here, and what it defers.** Green proves the **seams, the
call-site rule, the presentation, and the config shape** — all hermetically, with doubles. It does
**not** prove real speech (FTHR-036), the first-run absent-voice UX (FTHR-037), real playback or
barge-in (FTHR-038), or anything audible (FTHR-039's smoke). This feather's honesty note is that it
is pure scaffolding: correct seams and rules, zero sound. Molt evidence should say exactly that.

## Acceptance Criteria

- [ ] AC-1: The tests listed above were observed failing before implementation and pass after.
- [ ] AC-2: The audio surface exposes `Renderer` (text → audio) and `Player` (audio → device)
      **seams** as Protocols alongside FTHR-028's input seams, with doubles supplied, and a turn's
      final answer flows answer → `Renderer` → `Player` through them — proven with no audio hardware
      (satisfies PLM-009 FC-1, FC-11 at the seam level).
- [ ] AC-3: Only the engine's **final answer** is handed to the `Renderer`; **tool activity is
      never** rendered to speech, asserted at the speak call site with a recording double (satisfies
      PLM-009 FC-8).
- [ ] AC-4: Heard and spoken text are presented with **distinct tags and distinct colours**
      (`[heard]`/`[spoken]`), proven as a pure function of (text, tag) with no device (satisfies
      PLM-009 FC-9).
- [ ] AC-5: The audio **output device is configuration, defaulting to the system default** when
      unset, mirroring the input-device config; proven at the seam with a double (satisfies PLM-009
      FC-5).
- [ ] AC-6: Voice, output-device, and presentation settings live in `config/audio.yaml` and load
      via the shared facility; **`voice` has no shipped default** (an unset voice is representable as
      missing, for FTHR-037 to turn into the first-run error) (satisfies PLM-009 FC-2 at schema
      level, FC-12).
- [ ] AC-7: This feather **extends FTHR-028's single audio surface and its one config file** — it
      defines the output seams and speaking schema **once**; it adds no second surface and no second
      config file. Any seam/schema insufficiency a downstream feather hits is raised as a finding
      here, not worked around in that feather (keeps wave 2 disjoint).
- [ ] AC-8: This feather contains **no piper/TTS**, **no real device playback**, **no voice
      download**, and **no barge-in** — those are FTHR-036/037/038; it ships doubles only. No
      speculative abstraction beyond the two seams, the three config keys, and the presentation
      function the tests exercise.
- [ ] AC-9: The **listening input path is untouched** (no edits to endpoint/STT/wake stages) and the
      engine is not modified; `ruff check .` is clean and the full existing test suite passes.
