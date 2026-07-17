---
id: FTHR-039
title: "Real-stage speaking pipeline: integration and audible/interruption smoke"
plumage: PLM-009
status: egg
priority: P1
depends_on: [FTHR-036, FTHR-037, FTHR-038, FTHR-029]
authored: 2026-07-17T16:15:08Z
agent: fledge-orchestrate/planning
fledge_version: 0.6.8
---

# FTHR-039: Real-stage speaking pipeline: integration and audible/interruption smoke

## Description

The composition proof for the speaking half — the speaking-side counterpart of FTHR-033. Every
feather before it proves a piece against doubles: FTHR-036's renderer with piper mocked, FTHR-037's
acquisition with the fetcher injected, FTHR-038's barge-in against a `Player` double and a **wake**
double. **Nothing yet runs the real render → real playback → real-wake barge-in chain wired
together, and nothing yet makes a sound.** This feather does both: an **automated composition proof**
that the real stages agree at their seams, and a **manual smoke** where the deferred acoustic claims
finally land on real hardware.

**It is the only PLM-009 feather that touches the real wake detector.** Barge-in was built (FTHR-038)
against FTHR-028's wake *seam* with a double precisely so it was provable before real wake existed;
here the **real `vesta.onnx` detector (FTHR-029)** composes in, so a real spoken "Vesta" mid-playback
is what interrupts. That is why this feather depends on **FTHR-029** — mirroring how FTHR-033 was the
listening-side proof that pulled in the real stages.

**It is the home of three deferred acoustic claims — discharge each by name:**
- **FTHR-036 deferred real audible output** — that piper actually produces intelligible speech, at
  usable latency on the Pi. Its CI mocked piper.
- **FTHR-037 deferred the real download + whether the first-run message reads well** — a real absent
  voice, actually fetched, and the absent-voice error actually read as a config step by a human. Its
  CI injected the fetcher and asserted message *fragments*, not prose quality.
- **FTHR-038 deferred real physical-stop interruption** — that a real wake spoken mid-speech actually
  **cuts Vesta off** through a real device, and that real duplex device contention behaves. Its CI
  proved the interrupt *logic* against doubles.

If this feather's smoke does not exercise each, the deferral evaporated and the claim was never
tested anywhere. So the smoke procedure (AC-13 of the plumage) is not boilerplate — it is where
three explicitly-deferred claims come due.

**The through-speakers self-interruption is expected to appear in the smoke — and that is the point,
not a failure.** Run without headphones, Vesta's own voice may trip her wake word and cut her off:
the Known Limitation (PLM-009 Known Limitations Accepted) **manifesting**. The smoke must note it as
the accepted AEC-deferral tradeoff made visible — confirmed with headphones removing it — **not**
recorded as a smoke failure. Seeing it is the evidence the tradeoff is conscious; the mitigation
(headphones) is what makes normal use fine.

**Scope honesty.** The automated half is hermetic-composition only where it can be (piper mocked at
its edge per FTHR-036, no voice download in CI); real sound, real intelligibility, real acoustic
interruption, and real duplex contention are **only** the manual smoke. This feather must not claim
those are proven by CI.

**Depends on FTHR-036, FTHR-037, FTHR-038** (the three real speaking stages) **and FTHR-029** (real
wake for real barge-in). Runs in **wave 3**, after the wave-2 siblings.

## Affected Modules

See `.fledge/nest/architecture.md` → the audio surface and request path; `MANUAL_SMOKE.md` (the
existing smoke procedure — FTHR-033 added the live-microphone listening section; **extend it**, match
its style); FTHR-035's seams, FTHR-036/037/038's real stages, FTHR-029's real wake detector.

- `tests/test_audio_speaking_e2e.py` (new) — the assembled speaking integration test: real
  `Renderer` (piper mocked at its library edge), real `Player` (driven to an injectable sink so CI
  needs no device), real barge-in wiring, and the **real wake detector** (`vesta.onnx`, committed —
  no download), composed behind the surface. Asserts answer → rendered frames → playback, and a wake
  during playback stops it and opens a turn — through the **real** stages, no seam doubles.
- `MANUAL_SMOKE.md` — a new **speaking** procedure section: audible speech, the first-run voice
  step, real mid-speech interruption, and the self-interruption-without-headphones observation.

**Files this feather must NOT touch:** the stage modules and seams (`hearth/audio/**`) — this feather
**composes** them, it does not modify them. If integration reveals a stage or seam is wrong, that is
a **finding against the owning feather** (FTHR-035/036/037/038), not a fix smuggled in here — the
FTHR-033 rule. No AEC (FTHR-038's guard still holds; the self-interruption is observed, not fixed).

## Approach

**1. The assembled composition test (FC-11 boundary).** Wire the **real** render, playback, and
barge-in stages plus the **real wake detector** behind the surface, with exactly two substitutions:
piper is mocked at its library edge (FTHR-036's constraint — no ~voice-model download in CI) and the
`Player`'s device is the **injectable sink** (FTHR-038's Q7 — no sound card in CI). The wake detector
runs the real committed `vesta.onnx` (no download). Assert: a final answer flows answer → real
renderer → real player to the sink; and a **real** wake event during playback stops the player and
opens a turn. This is the first test exercising the **real inter-stage boundaries** — renderer output
feeding the player, wake feeding the barge-in — so a frame-format or lifecycle disagreement two green
unit suites hid **fails here**, not in the user's kitchen.

**2. Make boundary disagreements fail here.** Assert the frames the real renderer produces are what
the real player consumes (format/sample-rate), and that the real wake event drives the real stop. If
composing the real stages needs an adapter none of them owns, that adapter's absence is a **finding
against FTHR-035's seam definitions**, not something invented here.

**3. The manual smoke (AC-13) — where the three deferred claims come due.** Extend `MANUAL_SMOKE.md`
with a speaking section, in the existing style, that a human runs on real hardware. Each step names
the feather whose deferral it discharges:
- **Audible speech (FTHR-036's deferral):** with a real voice configured, ask something; Vesta
  **speaks the answer aloud**, intelligibly, at acceptable latency. The real piper doing real work
  CI deliberately did not prove.
- **First-run voice step (FTHR-037's deferral):** starting with **no voice configured**, confirm the
  surface refuses to start with a message that **reads as a config instruction** (names the setting,
  says where voices come from). Then name a voice, confirm it is **fetched on first run**, and that
  the second run does not re-fetch. The real download + the message reading well.
- **Real mid-speech interruption (FTHR-038's deferral):** while Vesta is speaking, **say "Vesta"** —
  playback **actually stops** and a new turn opens. The real wake model tripping mid-speech through a
  real device — the physical stop CI proved only in logic.
- **The Known Limitation, made visible:** run the interruption test **without headphones** and note
  whether Vesta's own voice trips her wake word and cuts her off. If it does, that is the
  **accepted AEC-deferral limitation manifesting** — record it as *expected*, confirm **headphones
  remove it**, and do **not** treat it as a smoke failure. This step is the conscious-tradeoff
  evidence.
- **End to end:** wake → speak a question → hear the spoken answer while the `[heard]`/`[spoken]`
  tagged transcript prints.

**4. State the boundary in the doc.** CI proves the stages *compose*; it does **not** prove audible
sound, intelligibility, real acoustic interruption, or real duplex contention — those are the manual
steps above. A reader must not mistake a green CI run for a working voice.

**Constraints.** Composes, does not modify. Real stages except the two external edges (piper library,
the device sink). Smoke steps map 1:1 to the deferred claims. The self-interruption is observed and
explained, never "fixed." No AEC.

## Tests

Test-first: (1) write; (2) run against the unchanged (pre-composition) tree, confirm FAIL for the
expected reason; (3) implement the wiring until they pass.

- `test_supplied_answer_runs_the_real_speaking_chain_to_the_sink` (new) — real renderer (piper
  mocked at its edge) + real player (to the injectable sink), composed behind the surface, turn a
  final answer into frames dispatched to the sink. **The FC-1 assembled proof.** *Fails before:* no
  speaking composition exists.
- `test_real_wake_interrupts_real_playback` (new) — with the **real `vesta.onnx`** detector composed
  in, a wake event during real-player playback stops the player and opens a turn — the real-stage
  barge-in (FTHR-038 proved this against a wake double; here it is the real detector). *Fails
  before:* real wake not composed with playback. FC-6 at the real-stage level.
- `test_real_stage_boundaries_agree` (new) — the frames the real renderer produces are well-formed
  for the real player (format/sample-rate), and the real wake event drives the real stop; written so
  a genuine inter-stage mismatch **fails here**. *Fails before:* composition not wired. The test
  whose job is to fail in CI instead of in the user's kitchen.
- `test_speaking_pipeline_is_hermetic` (new) — the assembled test triggers **no** voice-model
  download and needs **no** audio device: piper mocked, sink injected, `vesta.onnx` committed. Guards
  the hermetic property of the *integration*. *Fails before:* n/a until wired; a guard.

**What CI proves here, and what only the smoke can.** CI proves the **real stages compose** — real
renderer feeds real player, real wake drives the real stop, hermetically. CI does **not** prove
audible speech, intelligibility, real acoustic mid-speech interruption, or real duplex device
contention — those are the three deferred claims (FTHR-036/037/038), provable **only** on real
hardware in the manual smoke. Molt evidence must record **both**: the green assembled test
(composition proven) **and** the completed manual smoke (the three deferrals discharged, and the
self-interruption limitation observed-and-accepted). A green CI run alone leaves all three
promissory notes outstanding.

## Acceptance Criteria

- [ ] AC-1: The tests listed above were observed failing before implementation and pass after.
- [ ] AC-2: The **real speaking pipeline** is exercised end to end — final answer → real renderer →
      real player → sink, with a **real-wake** barge-in stopping playback — the real stages composed
      (piper mocked at its library edge per FTHR-036; the `Player` driven to an injectable sink per
      FTHR-038; **real `vesta.onnx`** for wake), and CI requires **no audio device and no model
      download** (satisfies PLM-009 FC-1, FC-6, FC-11 at composition level).
- [ ] AC-3: A test asserts the **real inter-stage boundaries agree** (renderer→player frame
      format/sample-rate; real wake→real stop), written so a genuine mismatch between two
      individually-passing stages **fails in CI** rather than at runtime — the composition guarantee
      this feather exists for.
- [ ] AC-4: This feather **composes** the stages and modifies none of them; any stage/seam defect
      integration reveals is raised as a finding against the owning feather (FTHR-035/036/037/038),
      not fixed inside the integration test.
- [ ] AC-5: `MANUAL_SMOKE.md` gains a **speaking** procedure that discharges the three deferred
      claims, each step naming the feather it covers: **audible speech** (FTHR-036), **first-run
      voice step — real download + message reads as config** (FTHR-037), and **real mid-speech
      acoustic interruption** (FTHR-038), plus a full wake→speak→heard-spoken-tagged walk (satisfies
      PLM-009 AC-13).
- [ ] AC-6: The smoke includes running the interruption **without headphones** and records whether
      the through-speakers **self-interruption** manifests — noted as the **accepted AEC-deferral
      Known Limitation made visible** (confirmed removed by headphones), **not** as a smoke failure
      (satisfies PLM-009 Known Limitations Accepted).
- [ ] AC-7: The smoke doc and this feather state that **CI proves composition only**; audible sound,
      intelligibility, real acoustic interruption, and real duplex contention are provable **only** in
      the manual smoke — nothing claims a green CI run is a working voice.
- [ ] AC-8: Molt evidence records **both** the green assembled CI test (composition proven) **and**
      the completed manual smoke (three deferrals discharged + self-interruption observed-and-
      accepted); a green CI run alone is documented as leaving the three claims outstanding.
- [ ] AC-9: Only `tests/test_audio_speaking_e2e.py` and `MANUAL_SMOKE.md` are added/changed; no
      `hearth/audio/**` file is modified, and **no AEC** is introduced (FTHR-038's guard holds — the
      self-interruption is observed, not fixed).
- [ ] AC-10: `ruff check .` is clean and the full existing test suite passes.
