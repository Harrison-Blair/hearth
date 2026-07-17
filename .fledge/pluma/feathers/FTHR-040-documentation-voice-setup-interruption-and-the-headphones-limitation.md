---
id: FTHR-040
title: "Documentation: voice setup, interruption, and the headphones limitation"
plumage: PLM-009
status: egg
priority: P1
depends_on: [FTHR-035, FTHR-036, FTHR-037, FTHR-038, FTHR-039]
authored: 2026-07-17T16:17:35Z
agent: fledge-orchestrate/planning
fledge_version: 0.6.8
---

# FTHR-040: Documentation: voice setup, interruption, and the headphones limitation

## Description

Makes the project's documentation tell the truth about the speaking capability PLM-009 delivered.
The speaking half now exists — Vesta renders answers to speech, plays them, is interruptible by her
wake word, requires a named voice and fetches it on first run — and none of that is documented yet.
This feather documents exactly what shipped, and no more. It is the speaking-side counterpart of
FTHR-034 (the listening docs), and it carries the same discipline: **current, correct claims only —
no aspirational text about capabilities no feather built.**

Three things to document:

1. **The voice setup step (FC-13).** A voice is **required and none ships** — name one in
   `config/audio.yaml` (the `voice` key FTHR-035 defined) and it is **fetched on first run**
   (FTHR-037). Document naming the voice, where voices come from (the same pointer the first-run
   error gives), and that the first run performs the fetch — so a reader knows the surface will not
   start until a voice is named, and why that is intended, not a bug.

2. **How interruption works (FC-13).** **Say the wake word during playback to interrupt** — Vesta
   stops and starts a new turn (FTHR-038). Document it as deliberate interruption by name, and that
   only the wake word interrupts (not any nearby sound), matching the plumage's decision.

3. **The headphones Known Limitation — this feather OWNS it.** FTHR-038 deliberately did **not**
   write this; it belongs here. Through speakers, Vesta's microphone stays live while she speaks, so
   **she can hear herself** and her own voice can trip her wake word and cut her off. **Headphones
   are the interim mitigation** (they remove the echo path). Echo cancellation is a **conscious
   deferral, not a missing feature** — the `aec` dependency is a native build unvalidated on the Pi,
   deferred to a future plumage. Document this as an accepted limitation with a mitigation, in the
   plumage's own framing (PLM-009 Known Limitations Accepted), so a reader understands it is a
   deliberate tradeoff, not an oversight.

**Honesty (the FTHR-034 discipline).** Document what the speaking surface **does today**: it speaks
the engine's **final answer** aloud (never tool activity), prints the `[heard]`/`[spoken]` tagged
transcript alongside, is interruptible by the wake word, and requires a named voice. Do **not**
describe voice tuning, streaming/incremental speech, voice auditioning/listing, or AEC — none of
those shipped (all are PLM-009 Out of Scope). If a doc line would describe behavior no feather
delivered, that is a **finding to raise, not prose to write**.

**Runs in wave 4, after FTHR-039** — it documents the assembled, working speaking surface. Depends
on all of FTHR-035–039 (the surface, the stages, and the integration/smoke it describes).

## Affected Modules

See `.fledge/nest/index.md`; the docs FTHR-034 established for the audio surface (extend them for
speaking — match their style and placement); `config/audio.yaml` and its defaults (the `voice` and
output-device keys the setup doc references); `MANUAL_SMOKE.md` (FTHR-039's speaking smoke — the
docs should be consistent with it, but the procedure itself lives there, not here).

- `README.md` — the working/roadmap table: **speaking (TTS/voice output + barge-in) moves from
  roadmap toward working** — state it precisely (voice output lands; AEC/echo-handling remains
  roadmap). Plus prose for the voice setup step and interruption if the README is where the audio
  surface is introduced.
- `CLAUDE.md` — if it describes the audio surface as listening-only (FTHR-034 framed it that way,
  correctly for its time), update that framing to include speaking; add the `voice`/output-device
  config keys to the config-section description if it enumerates them. Check against the finished
  state before editing.
- The audio-surface guide / config reference (wherever FTHR-034 documented `config/audio.yaml`) —
  add the `voice` (required, no default), output-device, and presentation/tagging keys, how a voice
  is named and fetched, how interruption works, and the headphones limitation.

**Do NOT touch `.fledge/`** — fledged specs and molt evidence are historical records, never
rewritten. **Do NOT rewrite unrelated doc sections** — document PLM-009's surface, leave the rest.
No code, no seams, no tests of runtime behavior.

## Approach

Work from the **finished code and config**, not from this description — key names and commands must
match what actually shipped. `grep` the shipped `config/audio.yaml` for the real `voice` and
output-device key names; confirm the run command and the first-run behavior against FTHR-037/039
before writing them down.

**What must be true after this feather:**

1. **The voice setup step is documented and correct:** a voice is required, none ships, name it in
   `config/audio.yaml` under the real key, it is fetched on first run; the surface will not start
   without one (intended). The key name and file match the shipped config.
2. **Interruption is documented:** say the wake word during playback to interrupt; only the wake word
   interrupts; Vesta stops and opens a new turn.
3. **The headphones Known Limitation is documented** as an accepted tradeoff with headphones as the
   mitigation and AEC as a conscious future deferral — not a bug, not a missing feature.
4. **The working/roadmap status is accurate:** voice output + barge-in have landed; echo
   cancellation / comfortable speaker use remains roadmap.
5. **Nothing overstated:** no voice tuning, no streaming speech, no voice auditioning/listing, no
   AEC — none shipped.

**Constraint.** Prose (plus possibly the README status table). Document only what shipped. Do not
touch `.fledge/`. If a doc claim is uncertain against the finished code, verify it in the code/config
rather than guessing — the whole point, as with FTHR-034, is docs that match reality.

## Tests

**No unit tests for prose — inventing one would be theatre**, the same honest position as FTHR-034
and FTHR-027. `pytest` asserts nothing on doc content, and a keyword grep pins a word, not the truth
of the sentence around it. What is mechanically verifiable, and must be recorded as molt evidence:

- **The documented config keys exist in the shipped config.** `grep` the `voice` and output-device
  key names the docs reference and confirm they are the real keys in `config/audio.yaml` — a
  documented setting that does not exist is the failure this check catches (the FTHR-034 AC-4
  lesson: a documented command/key that does not resolve fails in a user's hands).
- **Any documented command is executed as written** where runnable (e.g. the run command for the
  audio surface resolves; the first-run behavior is as described). A stale instruction is a defect.
- **No doc claims a capability PLM-009 did not ship** — confirm no prose describes voice tuning,
  streaming speech, voice listing/auditioning, or AEC as available. (AEC appears only as the
  documented deferred limitation, never as a feature.)
- The existing test suite still passes (docs-only change; nothing should break, but confirm).

## Acceptance Criteria

- [ ] AC-1: Documentation covers the **voice setup step** — a voice is required with **no shipped
      default**, named in `config/audio.yaml` under its real key, and **fetched on first run**; the
      documented key name and file match the shipped config (satisfies PLM-009 FC-13).
- [ ] AC-2: Documentation covers **interruption** — say the **wake word** during playback to
      interrupt; only the wake word interrupts; Vesta stops and opens a new turn (satisfies PLM-009
      FC-13).
- [ ] AC-3: Documentation covers the **headphones Known Limitation** — through speakers Vesta can
      trip her own wake word; **headphones are the mitigation**; **AEC is a conscious deferral, not a
      missing feature**. This feather **owns** the Known-Limitation docs FTHR-038 did not write
      (satisfies PLM-009 FC-13, Known Limitations Accepted).
- [ ] AC-4: The **working/roadmap status is accurate** — voice output + wake-word barge-in have
      landed; echo cancellation / comfortable speaker use remains roadmap. Nothing overstates the
      speaking surface.
- [ ] AC-5: **No doc claims a capability PLM-009 did not ship** — no voice tuning, streaming speech,
      voice listing/auditioning, or AEC-as-feature; AEC appears only as the deferred limitation. Any
      such line would be a finding, not written.
- [ ] AC-6: The documented config keys and any documented command **match the shipped config/code**
      (verified against the finished tree, not this spec); `.fledge/` is untouched and unrelated doc
      sections are not rewritten.
- [ ] AC-7: `ruff check .` is clean and the full existing test suite passes (docs-only change).
