---
id: PLM-009
title: "Audio veneer: speaking path (text-to-speech, playback, and barge-in)"
status: hatched
priority: P1
authored: 2026-07-17T07:44:41Z
agent: fledge-orchestrate/planning
fledge_version: 0.6.7
---

# PLM-009: Audio veneer: speaking path (text-to-speech, playback, and barge-in)

## Context

This plumage gives hearth a voice. It is the second half of the voice capability: the
listening plumage gives the assistant ears and hands what it hears to the engine as text; this
one takes the engine's answer and says it aloud.

Today nothing speaks. The text-to-speech dependency is declared and unused, there is no voice
configuration, and — unlike the wake models, which are trained and committed — **no voice
exists in the project at all**. A voice is a separate downloadable artifact, and which one the
assistant should sound like is not yet decided.

That undecidedness is treated as a first-class fact rather than papered over. The assistant's
voice is the most immediately personal thing about it, and it is not a default worth
inheriting from convention or from another project. So this plumage **requires** a voice to be
named in configuration and **ships none**: the surface refuses to start without one and says
so plainly. Once named, the voice is fetched automatically if it isn't already present, so the
choice costs one configuration line and a first run — not a setup ritual.

The plumage also makes the assistant interruptible. Speech is slow, and an assistant that must
be waited out is one you stop talking to. Saying the wake word during playback stops her and
begins a new turn — deliberate interruption, by name, rather than anything that merely makes a
noise nearby.

Interruption has a consequence, and it is accepted with open eyes rather than deferred
silently. Being interruptible means the microphone stays live while the assistant is speaking,
which means **she can hear herself**. The clean fix for that is acoustic echo cancellation,
which needs a native dependency that has never been validated on the target device. Rather
than pull that in here, the interim mitigation is **physical**: headphones remove the echo
path entirely, and that is how the user intends to run it to begin with. The limitation this
leaves is real and is recorded below, not buried — through speakers rather than headphones,
the assistant's own voice can trigger her wake word and cut her off mid-sentence. Echo
cancellation is owed by a future plumage before speaker use is comfortable.

This plumage **extends the single audio surface** the listening plumage stands up (PLM-008's
spine): there is one audio veneer, and speaking is added to it rather than built as a second
surface. It therefore depends on that spine, and barge-in depends further on wake detection —
"the wake word during playback stops her" is the **acoustic** realisation of the *structural*
duplex the listening plumage's integration could only assert against test doubles, because
nothing spoke yet. Concretely: this plumage depends on the audio-surface spine (and, for
composing real barge-in, on the real wake detector), but it is **independent of the listening
input path** — endpointing and speech-to-text, which speaking never touches. That independence
is the accurate form of the earlier "built in parallel" intent: the speaking work can proceed
alongside the *tail* of the listening plumage, sharing only the spine and the wake detector, not
the whole of it. Barge-in itself is built against the surface's wake *seam* with a test double,
so the speaking path is provable before the real wake model is composed in.

## User Stories

- As the assistant's user, I want Vesta to answer out loud, so that I can use her without
  looking at a screen.
- As the assistant's user, I want to interrupt her by saying her name, so that I can redirect
  her without waiting out an answer I no longer want.
- As the assistant's user, I want to choose what she sounds like rather than inherit whatever
  voice someone picked for me, so that the assistant in my home sounds the way I want it to.
- As the assistant's user, I want the voice I named to install itself, so that choosing a voice
  costs a configuration line and not a setup procedure.
- As the assistant's user, I want to be told clearly what to set when I haven't chosen a voice
  yet, so that my first run explains itself instead of failing at me.
- As the assistant's user, I want to still see what she heard and what she said, distinctly
  marked, so that I can follow and debug a conversation while it happens aloud.
- As the assistant's user, I want silence rather than narration while she works, so that she
  isn't announcing her own internals at me.
- As a developer, I want speaking to be provable without a speaker, so that it is tested as
  hermetically as everything else and CI needs no audio hardware.

## Functional Criteria

1. FC-1: The audio surface renders the engine's final answer to speech and plays it on an
   audio output device.
2. FC-2: The voice is **required configuration with no shipped default**. The surface does not
   start without a voice named.
3. FC-3: When no voice is configured, the surface reports a clear, actionable message that
   names the missing setting and states how to discover valid voices, and exits as a
   configuration problem rather than a crash — no stack trace. This is the first thing a user
   meets, and it must read as an instruction, not a failure.
4. FC-4: On startup the surface checks whether the configured voice is present locally and
   fetches it if not, before it begins serving. A first run is therefore the setup step; no
   separate installation procedure is required.
5. FC-5: The audio output device is configuration, defaulting to the system default device,
   mirroring how the input device is configured.
6. FC-6: Speech playback is **interruptible by the wake word**. Detecting a wake word during
   playback stops playback promptly and begins a new turn from what follows.
7. FC-7: **The audio surface operates full duplex.** Interruption (FC-6) requires capture and
   playback to be active at the same time, which carries concrete obligations: a duplex-capable
   device or two independent streams; playback that never blocks or starves capture; and
   tolerance of shared-device contention on the target hardware. Wake detection during playback
   is not a special mode — it is ordinary continuous capture (the listening plumage's
   requirement) running while audio happens to be playing.
8. FC-8: Only the engine's final answer is spoken. Tool activity is never spoken.
9. FC-9: The surface continues to present heard transcripts and answers as text alongside
   speaking, with what was **heard** and what was **spoken** distinctly tagged and coloured, so
   a conversation can be followed and debugged as it happens.
10. FC-10: Everything presented — spoken or printed — passes through the shared safety policy;
    internal failure detail and tool internals never reach the user by any route, including
    aloud.
11. FC-11: Audio output leaves the pipeline through a seam that can be driven by a test sink
    instead of a device, so rendering and the playback lifecycle — including interruption — are
    provable without hardware and CI stays hermetic.
12. FC-12: Voice and playback settings live in the audio surface's own configuration file,
    loaded by the shared configuration facility.
13. FC-13: Documentation states that a voice must be chosen and named, how it is acquired, how
    interruption behaves, and the headphones limitation recorded below.

## Acceptance Criteria

- [ ] AC-1: A test demonstrates the engine's answer rendered to speech and dispatched to the
      output sink (FC-1, FC-11).
- [ ] AC-2: A test demonstrates the surface refusing to start with no voice configured, with a
      message naming the setting and how to discover valid voices, exiting non-zero without a
      stack trace (FC-2, FC-3).
- [ ] AC-3: A test demonstrates a configured-but-absent voice being fetched before serving
      begins, and an already-present voice not being re-fetched (FC-4).
- [ ] AC-4: A test demonstrates playback directed to the configured output device, defaulting
      to the system default when unset (FC-5).
- [ ] AC-5: A test demonstrates a wake word detected during playback stopping playback promptly
      and opening a new turn (FC-6).
- [ ] AC-6: A test demonstrates capture remaining active and wake detection remaining
      responsive *while playback is in progress*, and that playback neither blocks nor starves
      capture — the duplex property interruption depends on (FC-7).
- [ ] AC-7: A test demonstrates that tool activity is never rendered to speech while the final
      answer is (FC-8).
- [ ] AC-8: A test demonstrates heard and spoken text presented with distinct tags and colours
      (FC-9).
- [ ] AC-9: A test demonstrates an engine error surfacing through the shared safety policy with
      no internal detail spoken or printed (FC-10).
- [ ] AC-10: The speaking path is exercised end to end — answer to rendered audio to playback
      lifecycle, including interruption — with no audio hardware, and CI requires none
      (FC-11).
- [ ] AC-11: Voice and playback settings load from the audio surface's own configuration file
      via the shared facility (FC-12).
- [ ] AC-12: Documentation covers choosing and naming a voice, how it is acquired, how
      interruption behaves, the full-duplex requirement, and the headphones limitation
      (FC-13).
- [ ] AC-13: A manual verification procedure covers audible speech and live interruption on
      real hardware, since real playback, real barge-in, and genuine duplex device behavior are
      the parts not provable hermetically.
- [ ] AC-14: Every test in this plumage's feathers was written first and observed failing
      against the unchanged code for the expected reason before the implementation was
      corrected until it passed.
- [ ] AC-15: The full existing test suite passes.

## Known Limitations Accepted

- **Through speakers, the assistant can interrupt herself.** Interruption requires the
  microphone to stay live while she speaks (FC-6), so her own voice reaches it. Without echo
  cancellation, her speech can trigger her own wake word and cut her off mid-sentence. This is
  **accepted deliberately, not overlooked**: the interim mitigation is physical — headphones
  remove the echo path entirely, and that is how the user intends to run it initially. Echo
  cancellation is owed by a future plumage and should be considered a prerequisite for
  comfortable speaker use. The reasoning here is this plumage's own and does not rest on the
  listening plumage's — there, echo cancellation was excluded because nothing could speak yet;
  here something speaks, and it is excluded because the echo path is removed physically and the
  dependency that would fix it acoustically is unvalidated on the target device.

## Out of Scope

- **Acoustic echo cancellation.** Deferred to its own plumage, for the live reason recorded
  above. Its dependency is a native build, deliberately excluded from the default install
  pending validation on the target device; pulling it in here would put an unvalidated native
  dependency on the Pi as a side effect of adding a voice. Headphones are the interim
  mitigation.
- **Interruption by any speech other than the wake word.** Deliberately rejected: it would let
  a cough, a passing conversation, or a television cut her off. Interruption is by name, on
  purpose.
- **Speaking tool activity, or earcons for it.** Rejected (FC-8): a long consult is silence,
  then an answer. Tool activity remains visible as text.
- **Choosing the voice.** This plumage requires one and ships none, by decision. Naming a
  default would make the assistant's voice an inheritance rather than a choice.
- **A voice-audition or voice-listing subcommand.** A good error message pointing at how to
  discover voices is in scope (FC-3); a new command to browse or preview them is not.
- **Streaming or incremental speech.** The engine's contract delivers a final answer per turn;
  speaking begins when the answer is complete. Incremental synthesis is not attempted.
- **Voice tuning** — speed, pitch, prosody, or SSML-style control. Not asked for.
- **Per-surface release binaries.** Unchanged: still a separate packaging concern.
- **Wake-word training or the second wake model.** Settled and owned elsewhere.

## Open Questions

- **The voice is not yet chosen.** This is a decision the user has deliberately deferred until
  they can hear candidates, and this plumage is built so that deferral costs nothing: the voice
  is required configuration, so the choice is theirs whenever they make it, and naming it is
  all that is needed to activate it. Recorded because it means the audio surface **cannot run
  until a voice is named** — which is intended, but is a real first-run step, and the message
  a user meets at that moment (FC-3) is the whole of the guidance they will get.
- **Voice quality tiers trade size and CPU against naturalness, and the target device is a
  Raspberry Pi 5.** As with the transcription model in the listening plumage, the voice is
  configuration, so the Pi can run a lighter tier without a code change. Recorded so that if
  speech proves too slow or too heavy there, the knob to reach for is known and the finding is
  not mistaken for a defect.
