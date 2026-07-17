---
id: FTHR-033
title: "Real-stage listening pipeline: end-to-end integration and manual smoke"
plumage: PLM-008
status: egg
priority: P1
depends_on: [FTHR-029, FTHR-030, FTHR-031]
authored: 2026-07-17T15:48:06Z
agent: fledge-orchestrate/planning
fledge_version: 0.6.8
---

# FTHR-033: Real-stage listening pipeline: end-to-end integration and manual smoke

## Description

The composition proof. Every feather before this one proves a piece in isolation: FTHR-028's spine
is structurally duplex against *doubles*, and FTHR-029/030/031 each prove their own stage against
*controlled input*. **Nothing yet runs the real wake → real endpoint → real STT chain wired
together.** Two stages that each pass their own tests can still disagree at their shared boundary —
a frame format, a sample rate, an utterance-buffer shape — and today nothing would catch it until a
user spoke into a real microphone. This feather is the first thing that runs the assembled pipeline
(FC-11/AC-11), and it is written to **fail when the stages don't compose, not merely pass when they
do.**

It also **discharges the promissory notes** the wave-2 feathers wrote. Each deferred a real-world
claim to "FTHR-033's manual smoke":
- FTHR-029 deferred **real-acoustic wake reliability** (a person saying "Vesta" trips it; noise does
  not);
- FTHR-030 deferred whether the **endpoint timings feel right** (an utterance ends naturally, not
  cut off or hung);
- FTHR-031 deferred **real transcription accuracy** (real audio becomes correct text — its CI mocks
  the model by the user's Q4=A decision).

If this feather's manual smoke does not actually exercise each of those, the deferral evaporated and
the claim was never tested anywhere. So the smoke procedure (AC-15 of the plumage) is not
boilerplate here — it is where three explicitly-deferred claims finally land on real hardware.

**Scope honesty — this is the *listening* pipeline, and there is no voice yet.** FTHR-028 proved
*structural* duplex (capture continues while a turn is in flight). The **acoustic** reality —
microphone live *while a speaker plays* — cannot be proven until something plays, which is PLM-009.
This feather must not claim "end-to-end voice": it proves supplied/real audio → transcript →
submitted turn → **printed** answer. The speaker half, and the real mic-while-playback coexistence,
are PLM-009 + hardware. Be explicit about that boundary in both the tests and the smoke doc.

**Depends on FTHR-029, FTHR-030, FTHR-031** (the three real stages). FTHR-032 is not required — it
configures wake models but the integration can point config at `vesta.onnx` directly.

## Affected Modules

See `.fledge/nest/architecture.md` → *request path*; `MANUAL_SMOKE.md` (the existing live-service
smoke procedure — extend it, match its style).

- `tests/test_audio_pipeline_e2e.py` (new) — the assembled hermetic integration test: real
  FTHR-029/030/031 stages composed behind FTHR-028's spine, driven by a **supplied audio source**
  (FC-11), asserting a turn reaches the engine. Mirrors `tests/test_e2e_veneer.py`'s assembled-stack
  shape (real components, doubled only at the true external edges).
- `MANUAL_SMOKE.md` — a new **live-microphone** procedure section (AC-15) covering the three
  deferred claims on real hardware.

**Files this feather must NOT touch:** the stage modules and the spine (`hearth/audio/**`) — this
feather **composes** them, it does not modify them. If integration reveals a real stage or seam is
wrong, that is a **finding against the owning feather** (FTHR-028/029/030/031), not a fix smuggled
into the integration feather. An integration test that has to edit a stage to pass is reporting a
real defect — surface it.

## Approach

**1. The assembled hermetic test (FC-11/AC-11).** Wire the **real** wake, endpoint, and transcribe
stages into the real spine, with two substitutions and only two: the **audio source** is the
supplied-frames seam (no microphone), and **faster-whisper is mocked at its library boundary**
(FTHR-031's Q4=A constraint holds here too — the real ~800 MB model does not download in CI). Wake
runs the real committed `vesta.onnx` (no download). Feed supplied audio containing a wake trigger
followed by speech frames; assert a turn with the transcript reaches the engine (a doubled engine /
the e2e harness). This is the first test that exercises the **real inter-stage boundaries** —
wake's output feeding endpoint's input feeding transcribe's input.

**2. Make boundary disagreements fail here.** The value of this test is catching a mismatch two
green unit suites can hide. Drive it with audio whose shape is what a real source produces, and
assert the utterance handed to transcribe is well-formed — so a sample-rate or frame-format
disagreement between the real stages surfaces as a failed assertion in CI, not a mystery in the
user's kitchen. If composing the real stages requires an adapter that none of them owns, that
adapter's absence is a **finding against FTHR-028's seam definitions**, not something to invent
here.

**3. The manual smoke procedure (AC-15) — where the deferred claims land.** Extend `MANUAL_SMOKE.md`
with a live-microphone section, in the existing doc's style, that a human runs on real hardware:
- **Wake reliability (FTHR-029's deferral):** say "Vesta" — it wakes; stay silent / make ambient
  noise — it does not. The real trained model on real acoustics.
- **Endpointing feel (FTHR-030's deferral):** speak a sentence and stop — capture ends naturally
  after the trailing silence, neither cutting you off mid-word nor hanging; confirm the max-length
  cap by talking past it.
- **Transcription accuracy (FTHR-031's deferral):** say a known sentence — the printed transcript
  matches. This is the real faster-whisper model doing real work, the thing CI deliberately does
  not prove.
- **End to end:** wake, speak, see the heard transcript and the engine's answer **printed** (no
  voice — that is PLM-009).
Each step names which feather's deferred claim it discharges, so the smoke doc is auditable against
the promissory notes rather than being generic.

**4. State the duplex boundary in the doc.** Note explicitly that acoustic mic-while-playback
duplex is **not** covered here (nothing plays yet) and is owed by PLM-009 — so a reader does not
mistake listening-pipeline success for full-voice success.

**Constraints.** Composes, does not modify. Real stages except the two external edges (device, the
STT model per Q4=A). No claim of voice output. Smoke steps map 1:1 to the deferred claims.

## Tests

Test-first: (1) write; (2) run against the unchanged (pre-composition) code, confirm FAIL for the
expected reason; (3) implement the wiring until they pass.

- `test_supplied_audio_runs_the_real_stage_chain_to_a_turn` (new) — real wake+endpoint+transcribe
  (STT mocked at the library edge) behind the real spine, driven by supplied audio containing a
  wake trigger + speech, produce a turn carrying the transcript at the engine. **The FC-11 assembled
  proof.** *Fails before:* no integration wiring exists / the stages have never been composed.
- `test_real_stage_boundaries_agree` (new) — assert the utterance object wake→endpoint→transcribe
  hand across is well-formed at each boundary (frame format / sample rate / buffer shape as the real
  stages actually produce and consume). Written so a genuine inter-stage mismatch **fails here**.
  *Fails before:* composition not wired. This is the test whose job is to fail in CI instead of in
  the user's kitchen.
- `test_pipeline_is_hermetic` (new) — the assembled test triggers **no** model download and needs
  **no** audio device: `vesta.onnx` is the committed real model, faster-whisper is mocked, the
  source is supplied frames. Guards the hermetic property of the *integration* explicitly. *Fails
  before:* n/a until wired; guards against a later edit that reaches for a real device or model.

**What CI proves here, and what only the manual smoke can.** CI proves the **stages compose** —
the real inter-stage boundaries agree and an assembled pipeline carries a transcript to a turn,
hermetically. CI does **not** prove wake reliability, endpoint feel, or transcription accuracy on
real audio — those are the three deferred claims, and they are provable **only** on real hardware,
in the manual smoke. Molt evidence must record both: the green assembled test (composition proven)
**and** the completed manual smoke run (the deferred claims discharged). A green CI run alone leaves
all three promissory notes still outstanding.

## Acceptance Criteria

- [ ] AC-1: The tests listed above were observed failing before implementation and pass after.
      Guard tests marked "*Fails before:* n/a" are exempt from the fail-first requirement;
      instead they were shown failing when the guarded property is deliberately violated, then
      pass unmodified.
- [ ] AC-2: The **full listening pipeline** is exercised end to end from supplied audio to a
      submitted turn with the **real** wake/endpoint/transcribe stages composed (STT mocked at its
      library edge per Q4=A; wake runs the real `vesta.onnx`), and CI requires no audio hardware and
      no model download (satisfies PLM-008 FC-11, AC-11).
- [ ] AC-3: A test asserts the **real inter-stage boundaries agree** (the wake→endpoint→transcribe
      hand-across is well-formed), written so a genuine mismatch between two individually-passing
      stages fails in CI rather than at runtime. This is the composition guarantee that is the whole
      reason this feather exists.
- [ ] AC-4: This feather **composes** the stages and modifies none of them; any stage/seam defect
      revealed by integration is raised as a finding against the owning feather
      (FTHR-028/029/030/031), not fixed inside the integration test (satisfies the disjointness the
      wave depends on).
- [ ] AC-5: `MANUAL_SMOKE.md` gains a live-microphone procedure that discharges the three deferred
      claims — **wake reliability** (FTHR-029), **endpoint feel** (FTHR-030), **transcription
      accuracy** (FTHR-031) — each step naming the feather whose deferral it covers, plus a full
      wake→speak→printed-answer walk (satisfies PLM-008 AC-15).
- [ ] AC-6: The smoke doc and this feather **explicitly scope out voice output and acoustic
      mic-while-playback duplex** as owed by PLM-009; nothing here claims end-to-end voice or
      acoustic duplex — FTHR-028 proved only *structural* duplex, and the acoustic reality needs a
      speaker.
- [ ] AC-7: Molt evidence records **both** the green assembled CI test (composition proven) and the
      completed manual smoke (deferred claims discharged); a green CI run alone is documented as
      leaving the three real-acoustic claims outstanding.
- [ ] AC-8: Only `tests/test_audio_pipeline_e2e.py` and `MANUAL_SMOKE.md` are added/changed; no
      `hearth/audio/**` file is modified.
- [ ] AC-9: `ruff check .` is clean and the full existing test suite passes.
