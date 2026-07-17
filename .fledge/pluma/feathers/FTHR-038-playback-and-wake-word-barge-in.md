---
id: FTHR-038
title: Playback and wake-word barge-in
plumage: PLM-009
status: egg
priority: P1
depends_on: [FTHR-035]
authored: 2026-07-17T16:12:14Z
agent: fledge-orchestrate/planning
fledge_version: 0.6.8
---

# FTHR-038: Playback and wake-word barge-in

## Description

The crux of the speaking half. This feather supplies the **real `Player`** (audio frames → output
device) behind FTHR-035's seam, drives the playback lifecycle, and makes speech **interruptible by
the wake word** (FC-6): a wake detected *while audio is playing* stops playback promptly and opens a
new turn.

Barge-in is the **acoustic partner to FTHR-033's structural duplex**. The listening plumage proved
that capture continues while a turn is in flight — but it could only *assert* the mic-live-while-a-
speaker-plays case against doubles, because **nothing spoke yet**. This feather is where something
speaks, so it is where the interrupt path becomes real. It is built against FTHR-028's wake **seam**
with a **double**, so the interrupt is provable hermetically here; the real wake model composes in
only at FTHR-039.

Three things land here:

1. **The real device `Player`** implementing FTHR-035's `Player` Protocol — output device from
   config (default = system default, FC-5), the play lifecycle, and a **stop** the interrupt path
   drives. It **injects into FTHR-035's seam; it does not invent one** (an insufficient seam is a
   finding against FTHR-035).

2. **Wake-word barge-in (FC-6) — the deadlock-shaped interrupt.** While the `Player` is playing, a
   wake event from the wake seam **must actually stop playback and open a new turn**. The test for
   this is written so that a `Player` which *ignores* the interrupt **fails** — it cannot be a test
   that passes when barge-in is broken (see Tests).

3. **The duplex obligation this depends on (FC-7).** Capture stays live and wake detection stays
   responsive *while playback is in progress*; playback must **not block or starve capture**. This
   is not a special mode — it is FTHR-028's ordinary continuous capture running while audio happens
   to be playing. Proven with a controllable player double and the wake seam, no device.

**AEC stays deferred — guard this hardest; it is the most tempting thing to "fix."** Keeping the mic
live during playback means, through speakers, **Vesta can hear herself** and her own voice can trip
her wake word and cut her off. That is a **Known Limitation accepted by the user** (PLM-009 Known
Limitations Accepted), with **headphones as the interim mitigation** — the echo path removed
physically. **No feather may re-add echo cancellation to make this go away.** A brooder reaching for
`speexdsp` / a webrtc AEC is raising a **finding**, not adding a feature — the `aec` extra is
deliberately excluded from the default install pending validation on the target device, and pulling
it in here would put an unvalidated native dependency on the Pi as a side effect of playback. This
feather **does not touch AEC in any form**; it documents nothing about it either (FTHR-040 owns the
Known-Limitation docs).

**Boundaries.** No TTS/render (FTHR-036 — this feather plays frames it is given, it does not
synthesise them). No voice acquisition/first-run error (FTHR-037). No real wake model (FTHR-039
composes it) — barge-in here is against the wake **seam** with a double. Disjoint file from both
wave-2 siblings.

**Runs in wave 2, parallel with FTHR-036 (render) and FTHR-037 (acquisition).** Depends on
**FTHR-035** (the `Player` seam, output-device config); consumes FTHR-028's wake seam (available
transitively — FTHR-035 depends on FTHR-028) with a **double**, not the real detector.

## Affected Modules

See `.fledge/nest/index.md` and `.fledge/nest/architecture.md` → the audio surface; FTHR-035's
`Player` seam and output-device config; **FTHR-028's `WakeDetector` seam and continuous capture
loop** — the seam barge-in listens on and the duplex property it relies on.

- `hearth/audio/**` — the concrete device `Player` implementing FTHR-035's Protocol; the playback
  lifecycle and its **stop**; the barge-in wiring that turns a wake event during playback into
  stop-playback + open-a-turn. Reuse FTHR-028's capture loop and wake seam; do not restructure them.
- `config/audio.yaml` — read the output-device key FTHR-035 defined; do **not** add new schema here
  (if barge-in needs a knob FTHR-035 didn't define, that is a finding against FTHR-035).
- `tests/` — new test module for the play lifecycle, the deadlock-shaped barge-in interrupt, and the
  duplex non-starvation property.

**Files this feather must NOT touch:** the `Renderer` (FTHR-036), the voice-acquisition path
(FTHR-037), the seam **definitions** (FTHR-035 / FTHR-028 own them — implement/consume, don't
redefine), the real wake detector impl (FTHR-029 — use a double here), and **anything AEC**. The
engine is not modified.

## Approach

**1. Real `Player` behind the seam.** Implement FTHR-035's `Player` Protocol against the real output
device (config device, default system default). Expose a **stop** that halts playback promptly —
the interrupt path calls it. Keep the surface depending on the Protocol; inject this concrete like
every other real stage.

**2. Barge-in wiring.** Subscribe the playback lifecycle to the wake seam so that a wake event
**during** playback (a) stops the `Player` promptly and (b) opens a new turn from what follows —
exactly FTHR-028's ordinary capture producing a wake, but now with playback in progress to
interrupt. Nothing about this is a special capture mode.

**3. Make the interrupt provable hermetically with a controllable double.** Use a `Player` double
whose "playing" state is observable and whose stop is observable, and drive a wake event from a wake
double **while it is playing**. This is the injectable-sink (Q7) decision: the interrupt is proven
with no sound card. Real audible stop is FTHR-039's smoke.

**4. Do not touch AEC, and do not let the self-interruption "leak" into scope.** The
through-speakers self-trip is a documented Known Limitation; this feather neither mitigates it in
code nor pulls in the `aec` extra. If it feels unbearable, that is a finding for the user, not a fix.

**Constraints.** Inject into FTHR-035's seam; consume FTHR-028's wake seam with a double; output
device from config; **no AEC in any form**; no render, no acquisition, no real wake model. Hermetic —
CI needs no audio device. Match existing style; surgical.

## Tests

Test-first, and the barge-in test uses **break-and-restore** per the user's test rule: the interrupt
must be a wiring that, when removed, makes the test **fail**. (1) write; (2) run against the
unchanged tree (no `Player`, no barge-in) and confirm FAIL for the expected reason; (3) implement
until green; and for barge-in specifically, (4) temporarily disable the interrupt wiring and confirm
the test FAILS again, then restore — recorded in molt.

- `test_wake_during_playback_stops_player_and_opens_a_turn` (new) — **the deadlock-shaped interrupt,
  the crux.** With the controllable `Player` double actively "playing," a wake event from the wake
  double **stops the player** and **opens a new turn**. Written so a `Player` that **ignores** the
  interrupt does **not** reach the stopped/new-turn state and the test **fails** — it cannot pass
  when barge-in is broken. *Fails before:* no barge-in wiring exists; **and** on break-and-restore,
  fails again when the interrupt is disabled. FC-6 — the acoustic-duplex crux made hermetic.
- `test_capture_and_wake_stay_responsive_during_playback` (new) — capture remains active and the
  wake seam still delivers events **while the player is playing**; playback neither blocks nor
  starves capture. Shaped so a player that monopolises the loop (blocking capture) **fails**.
  *Fails before:* playback wiring doesn't coexist with capture. FC-7 — the duplex property barge-in
  depends on.
- `test_player_targets_configured_output_device_default_system_default` (new) — the real `Player`
  directs output to the configured device, defaulting to the system default when unset. Proven at
  the seam with the double. *Fails before:* no player / no device resolution. FC-5.
- `test_playback_is_hermetic` (new) — the play + interrupt path needs **no** audio device in CI (the
  double is the sink). Guards the hermetic property against a later edit reaching for a real device.
  *Fails before:* n/a until wired; a guard.
- `test_no_echo_cancellation_dependency_is_introduced` (new) — no `aec`/`speexdsp`/webrtc-AEC import
  or dependency is added by this feather; the self-interruption stays a documented limitation, not a
  code mitigation. *Fails before:* n/a; **guards the user's explicit AEC-deferred decision** so a
  brooder "fixing" the self-trip is caught.

**What CI proves here, and what only the smoke can.** CI proves the **interrupt path fires and stops
the player, and that capture/wake coexist with playback** — hermetically, with doubles. CI does
**not** prove that **sound physically stops** on real speakers, that a **real wake model** trips
mid-speech, or that real duplex device contention behaves on the Pi — those are real-acoustic
properties deferred to **FTHR-039's manual smoke** (real audible playback + real mid-speech
interruption). Molt evidence must record the green interrupt proof (including the break-and-restore
observation) **and** state that real audible interruption remains a promissory note discharged only
at FTHR-039. A green suite here is "the interrupt *logic* is correct," not "sound stopped."

## Acceptance Criteria

- [ ] AC-1: The tests listed above were observed failing before implementation and pass after;
      specifically, the barge-in interrupt test was observed **failing on break-and-restore** when
      the interrupt wiring is disabled, recorded in molt (the user's test rule).
- [ ] AC-2: A concrete device `Player` **implements FTHR-035's `Player` Protocol** (injects into the
      seam; defines none), plays frames to the **configured output device defaulting to system
      default**, and exposes a prompt **stop** (satisfies PLM-009 FC-1 playback half, FC-5).
- [ ] AC-3: A wake event **during playback stops playback promptly and opens a new turn**, proven
      with a controllable `Player` double and a wake double; the test is **deadlock-shaped** — a
      `Player` that ignores the interrupt **fails** it (satisfies PLM-009 FC-6). This is the crux.
- [ ] AC-4: **Capture stays active and wake detection responsive while playback is in progress**, and
      playback neither blocks nor starves capture; a test fails if the player monopolises the loop
      (satisfies PLM-009 FC-7, the duplex property).
- [ ] AC-5: The play + interrupt path is **hermetic** — CI needs no audio device (the injectable
      sink is the Q7 decision); a test guards it (satisfies PLM-009 FC-11 for playback).
- [ ] AC-6: **No echo cancellation is introduced in any form** — no `aec`/`speexdsp`/webrtc-AEC
      import or dependency; the through-speakers self-interruption remains a **Known Limitation**
      (owned by the plumage; documented by FTHR-040), not a code fix; a test guards this. Any urge to
      mitigate it in code is a finding, not licence.
- [ ] AC-7: This feather **injects into FTHR-035's/FTHR-028's seams** (Player, wake) and defines
      none; it does **no** TTS/render (FTHR-036), **no** voice acquisition (FTHR-037), and uses a
      **wake double, not the real detector** (FTHR-029/FTHR-039); any seam insufficiency was raised
      as a finding against the owning feather.
- [ ] AC-8: Molt evidence records that CI proves the **interrupt logic** (path fires, player stops,
      capture coexists) — **not** that sound physically stopped, that a real wake model trips
      mid-speech, or that real duplex contention behaves; those are deferred to FTHR-039's smoke.
- [ ] AC-9: `ruff check .` is clean and the full existing test suite passes.
