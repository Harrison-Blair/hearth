---
id: FTHR-028
title: "Audio surface spine: duplex capture loop and stage seams"
plumage: PLM-008
status: pipping
priority: P1
depends_on: []
authored: 2026-07-17T15:34:19Z
agent: fledge-orchestrate/planning
fledge_version: 0.6.7
---

# FTHR-028: Audio surface spine: duplex capture loop and stage seams

## Description

The tracer foundation for the listening path: a new `hearth-audio` veneer that captures audio
**continuously**, runs it through injected wake/endpoint/STT stages, submits the resulting
transcript to the engine over the wire, and presents what it heard and what came back. This
feather ships the **spine** — the surface, the capture loop, the stage seams, the config — and
exercises it against **stage doubles**. The real wake, endpointing, and transcription are
FTHR-029/030/031, plugged into the interfaces defined here.

**This feather owns the one criterion the whole plumage turns on: FC-15 duplex.** Capture is
continuous and independent of turn state — the surface does not stop listening while a turn is in
flight — and the input device is acquired **non-exclusively**, so audio can be captured while it
is played. PLM-009 (speaking) needs the microphone live *while* Vesta speaks; a spine built as a
sequential wake→capture→transcribe→answer loop would satisfy a naive reading of every other
criterion here and **make PLM-009 impossible without reworking this feather**. So duplex is not
prose in this body — it is AC-4 and AC-5, shaped so that a sequential implementation **cannot
pass** (see Tests). This is the user's own catch (PLM-008 was silent on duplex until they flagged
it) made structural.

**Depends on the whole of PLM-007** (plumage-level, not a feather edge): it is a veneer, so it
needs the veneer client contract (`hearth/veneers/base.py`), the shared config facility
(per-component `config/<name>.yaml`), and surface provenance (`run_turn(surface=...)` — the audio
surface declares `"audio"`). Author against the contract PLM-007 *defines*; build against whatever
PLM-007 *landed*.

**Ships no real wake/STT and no hardware capture in CI.** The audio source is behind an
injectable seam (FC-11); tests feed supplied frames. A real microphone is manual smoke (FTHR-033).

## Affected Modules

See `.fledge/nest/architecture.md` → *request path*, *veneer contract* (as PLM-007 leaves it);
`.fledge/nest/modules.md` → *veneer*.

- `hearth/audio/__init__.py`, `hearth/audio/surface.py` — the `hearth-audio` veneer: the capture
  loop, stage orchestration, output presentation, turn submission via the veneer contract with
  retry/backoff (FC-10).
- `hearth/audio/source.py` — the **injectable audio-source seam** (FC-11): a Protocol yielding
  audio frames, with a live-device implementation and a test-drivable supplied-frames
  implementation. The device implementation acquires the input **non-exclusively** (FC-15).
- `hearth/audio/stages.py` — the **stage interfaces**: `WakeDetector`, `Endpointer`,
  `Transcriber` Protocols (the seams FTHR-029/030/031 implement). **Only the interfaces and
  trivial test doubles live here** — no real implementation.
- `hearth/audio/config.py` (or a section in the surface) — the audio config model, **including
  the wake-model list schema**: an ordered list of `{path, threshold}` entries. This schema is
  the shared surface FTHR-029 *reads* and FTHR-032 *writes*; it is hoisted here so neither of
  those feathers defines it and they never collide on it.
- `config/audio.yaml`, `config/defaults/audio.yaml` — the audio surface's own config, loaded via
  PLM-007's shared facility with component `audio`. Holds only this surface's settings (FC-12):
  input device, the wake-model list, VAD/endpoint knobs, STT model+params, retry/backoff.
- `pyproject.toml` — `[project.scripts]` gains `hearth-audio`.
- `tests/test_audio_surface.py`, `tests/test_audio_source.py` — spine tests with stage doubles.

**Files this feather must NOT touch** (later feathers own them; naming them keeps wave 2 disjoint):
the real stage modules (FTHR-029/030/031 create their own files implementing `stages.py`'s
Protocols — this feather ships no real stage), `training/manifest.py` (FTHR-032), docs (FTHR-034).

## Approach

**1. The surface is a veneer.** Reuse `hearth/veneers/base.py` (PLM-007's client contract) for
connect / submit-turn / parse-inbound. Do **not** re-implement turn submission or reach into the
engine — the audio surface talks to the engine only over the wire, same as `chat`. It declares
its surface identity as `"audio"` (PLM-007 FTHR-025 made that a data value; use it, add no engine
branch).

**2. Retry with backoff (FC-10), not fail-fast.** This is the deliberate divergence from `chat`:
an unattended voice surface on a headless box must survive the engine starting later. PLM-007's
`base.py` fails fast; the audio surface wraps connection in retry-with-backoff here. If `base.py`
exposes a connect seam this can wrap cleanly, use it; if it doesn't, that is a finding to raise
(the contract may need a small seam), **not** a reason to copy `base.py`'s internals.

**3. The capture loop is continuous and turn-independent — this is the crux.** Structure it so a
single always-running task consumes frames from the source and feeds wake detection, *regardless
of whether a turn is currently outstanding with the engine*. When a wake fires and an utterance is
captured and transcribed, submitting it to the engine must **not** pause frame consumption. Model
it as: capture task (always running) → produces utterances → a separate concern submits them.
A design where `submit_turn()` is awaited inside the capture loop such that frames stop arriving
during the engine call **fails FC-15 and is the wrong shape.**

**4. Non-exclusive device acquisition (FC-15).** The live source opens the input device in a mode
that does not claim exclusive access, so PLM-009's playback can run concurrently. In CI this is
untested (no device); it is asserted structurally where possible and covered by manual smoke
(FTHR-033). Name the acquisition mode explicitly in the code so a reviewer can see it is
non-exclusive.

**5. Stage seams.** `WakeDetector.detect(frames) -> bool/event`, `Endpointer.accept(frame) ->
done?`, `Transcriber.transcribe(audio) -> str` — exact shapes are the implementer's call, but they
must be **injected** into the surface (constructor or factory), so FTHR-029/030/031 supply real
ones and tests supply doubles. Keep them minimal: define what the spine demonstrably needs to
orchestrate a turn, **nothing shaped for the real implementations' convenience** — those feathers
adapt to the seam, not the reverse. (Same discipline as PLM-007 FTHR-024's `base.py`: no
speculative surface for unbuilt callers.)

**6. Output presentation (FC-8, FC-9).** Print the heard transcript and the engine's answer; route
everything through PLM-007's shared safety policy so tool internals / error detail never reach the
surface. No speech — that is PLM-009.

**7. The wake-model schema (the hoist).** `[{path, threshold}]`, ordered, per-model threshold —
**no global threshold** (FC-3). Define it here as the audio config's shape. FTHR-029 reads it to
load and score models; FTHR-032 writes it from the registry. Neither redefines it. Add a short
comment at the schema naming both consumers, so a later editor knows it is shared surface.

**Constraints.** Config only in `config/audio.yaml`, no secrets in YAML (FTHR-015). No real
wake/VAD/STT here. No engine changes — if the surface seems to need one, raise it.

## Tests

Test-first: (1) write; (2) run against unchanged code, confirm each FAILS for the expected reason;
(3) implement until they pass. All use stage doubles and the supplied-frames source — no hardware.

- `test_supplied_audio_drives_a_turn_end_to_end` (new, `test_audio_surface.py`) — supplied frames
  containing a (doubled) wake trigger produce a captured utterance, a (doubled) transcript, a turn
  submitted via the contract, and the answer presented. The spine's tracer proof. *Fails before:*
  no surface exists.
- `test_capture_continues_while_a_turn_is_in_flight` (new) — **AC-4's evidence, the load-bearing
  duplex test, deadlock-shaped.** Inject a submit-seam that **blocks** (does not complete) and
  feed more frames while it is blocked; assert the capture loop **still consumes them and still
  detects a second wake**. Structure it so a sequential implementation — one that awaits the
  submit inside the capture path — **cannot pass: it stalls and the test times out** against a
  bounded deadline, rather than mis-asserting. A serial loop does not fail an assertion here; it
  fails to make progress. That is the PLM-007-F5 bar: a test that cannot pass when the behavior is
  wrong. *Fails before:* no capture loop.
- `test_input_device_acquired_non_exclusively` (new, `test_audio_source.py`) — the live source
  requests the device in a non-exclusive mode; assert on the acquisition parameters (not on a real
  device). Proves FC-15's device clause structurally. *Fails before:* no source.
- `test_unreachable_engine_is_retried_with_backoff` (new) — with the engine unreachable the
  surface retries (bounded, backing off) rather than exiting; once reachable, it proceeds.
  Contrast with `chat`'s fail-fast. *Fails before:* no retry. Satisfies FC-10.
- `test_audio_config_loads_independently_and_carries_wake_schema` (new) — the surface loads
  `config/audio.yaml` via the shared facility with the engine's config absent, and the wake-model
  list parses as ordered `{path, threshold}` entries with per-model thresholds. Pins FC-12 and the
  hoisted schema. *Fails before:* no audio config model.
- `test_surface_presents_via_safety_policy` (new) — a tool-activity/error event reaches the output
  only through the shared safety policy; no internal detail leaks. *Fails before:* no presentation.

**What a green suite here does NOT prove, and where that is covered.** These tests use doubled
stages and a supplied source. They prove the **spine orchestrates and is duplex-shaped**; they do
**not** prove any real wake/VAD/STT works (FTHR-029/030/031) nor that a real microphone or real
non-exclusive playback coexist on the Pi (FTHR-033 manual smoke). AC-4 proves the loop is
*structurally* duplex; the *acoustic* reality of capturing while playing is PLM-009 + hardware.
Say so in the molt evidence rather than letting a green spine read as "duplex works end to end."

## Acceptance Criteria

- [ ] AC-1: The tests listed above were observed failing before implementation and pass after.
- [ ] AC-2: `hearth-audio` runs as its own veneer process, reaching the engine only over the wire
      via PLM-007's client contract, declaring surface `"audio"`; it holds no in-process reference
      to engine internals (satisfies PLM-008 FC-1).
- [ ] AC-3: Wake, endpointing, and transcription are consumed through **injected interfaces**
      defined in this feather; the spine runs against doubles with no real stage present, so
      FTHR-029/030/031 implement the seams without modifying the spine (satisfies FC-1's
      contract-first intent).
- [ ] AC-4: **Capture is continuous and independent of turn state.** A test proves frames are
      still consumed and a second wake still detected while a turn submission is outstanding, and
      it is structured so a sequential (submit-inside-capture) implementation **times out rather
      than passing** (satisfies PLM-008 FC-15, AC-16). This is the criterion the plumage turns on;
      if a sequential spine can pass it, the test is wrong.
- [ ] AC-5: The input device is acquired **non-exclusively**; a test asserts the acquisition mode,
      and the code names it explicitly for a reviewer (satisfies PLM-008 FC-15, AC-17).
- [ ] AC-6: The surface **retries with backoff** when the engine is unreachable rather than
      exiting, and proceeds once it is reachable; a test covers both (satisfies PLM-008 FC-10).
- [ ] AC-7: The audio surface loads only `config/audio.yaml` via PLM-007's shared facility, with
      the engine's config absent; a test asserts independent load (satisfies PLM-008 FC-12).
- [ ] AC-8: The audio config defines the **wake-model list schema** as ordered `{path, threshold}`
      entries with per-model thresholds and **no global threshold**; the schema is defined **only
      here**, annotated as shared surface for FTHR-029 (reader) and FTHR-032 (writer) (satisfies
      PLM-008 FC-3; enables FC-2/FC-4 without collision).
- [ ] AC-9: Heard transcript and engine answer are presented through PLM-007's shared safety
      policy; a test shows no tool internals or error detail reach the surface (satisfies PLM-008
      FC-8, FC-9). No speech is produced (that is PLM-009).
- [ ] AC-10: This feather adds **no real wake/VAD/STT implementation** and **no** change to
      `training/manifest.py` or docs, leaving FTHR-029/030/031/032/034 their files (disjointness
      for wave 2).
- [ ] AC-11: `ruff check .` is clean and the full existing test suite passes.
