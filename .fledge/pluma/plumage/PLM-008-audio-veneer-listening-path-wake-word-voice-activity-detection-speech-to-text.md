---
id: PLM-008
title: "Audio veneer: listening path (wake word, voice activity detection, speech-to-text)"
status: hatched
priority: P1
authored: 2026-07-17T07:28:45Z
agent: fledge-orchestrate/planning
fledge_version: 0.6.7
---

# PLM-008: Audio veneer: listening path (wake word, voice activity detection, speech-to-text)

## Context

hearth is described as a voice assistant, but nothing in it listens. The wake-word groundwork
is real and finished — a training pipeline, a trained and gate-passing wake model, a model
registry — yet no part of the running system consumes any of it. The assistant's ears exist
as artifacts on disk and nowhere else.

This plumage gives hearth its ears: a new user surface that waits for a wake word, captures
what is said, turns it into text, and hands that text to the engine as a turn. It is the first
half of the voice capability the user asked for. Speaking back is the following plumage.

It builds on the veneer platform (PLM-007), which established that a surface is a **separate
process** reaching the engine only over the wire, with its own configuration and a shared
safety boundary. This plumage is the first real proof of that contract: an entirely different
kind of surface — nothing connects *to* it, and it is driven by a microphone and a model
rather than by someone typing — implemented against the same contract as the chat veneer, with
no engine changes required to accommodate it. If the platform is right, this surface plugs in;
if it isn't, this is where that shows.

The wake words themselves are already settled and are not revisited here: **Vesta** and
**Prometheus**, both wired as simultaneous triggers, Calcifer retired entirely. That decision
and its training work are complete.

However, only the **Vesta** model has actually been trained. Producing the Prometheus model
requires specific GPU hardware and hours of wall-clock that belong to the user, not to this
plumage. This plumage therefore treats the set of active wake models as **data, not
structure**: it supports as many models as the registry names, and works correctly with the
one that exists today. Prometheus becomes active when its model is trained, with no code
change. Project documentation currently claims both models already exist; that claim is
corrected here.

The speech-to-text choice is inherited rather than invented: the user's stenographer project
is a working offline dictation daemon that already settled this question against real use, and
its proven configuration is adopted as this surface's default rather than re-derived.

This plumage ships a surface that is **usable and verifiable on its own**, before anything can
speak: you say a wake word, you say a thing, and you see what was heard and what came back.

## User Stories

- As the assistant's user, I want to say "Vesta" (or "Prometheus") and have hearth start
  listening, so that I can reach the assistant without touching a keyboard.
- As the assistant's user, I want hearth to work out on its own when I have finished speaking,
  so that I can just talk and stop, without pressing anything to signal the end.
- As the assistant's user, I want to see what hearth heard and what it answered while there is
  still no voice output, so that I can confirm its ears work before it has a mouth.
- As the assistant's user, I want the voice surface to keep trying when the engine isn't up
  yet, so that a device starting everything at once doesn't leave me with a silent assistant
  that has quietly given up.
- As the assistant's user, I want a wake word to become active by training it and pointing the
  configuration at it, so that adding the second wake word later needs no code change.
- As the assistant's user, I want the voice settings that matter — which models, how sensitive,
  how long a pause ends my sentence — to be configuration, so that I can tune them on the
  target device without touching code.
- As a developer, I want the listening pipeline to be provable without a microphone, so that it
  is tested in the same hermetic way as everything else and CI needs no audio hardware.

## Functional Criteria

1. FC-1: A new user surface listens on an audio input device and activates on a wake word. It
   is a separate process implementing the established veneer contract, reaching the engine only
   over the wire.
2. FC-2: The surface supports **multiple simultaneously-active wake models**, any of which
   triggers it. The active set is configuration, not code: it works with the single trained
   model available today and requires no code change when another is added.
3. FC-3: Each wake model's detection threshold is **its own**, carried alongside that model in
   configuration. There is no single global threshold shared across models.
4. FC-4: The model registry's selection step writes both each model's location **and** its
   corresponding threshold into the audio surface's configuration, so the operating point
   established by training reaches the runtime without being copied by hand.
5. FC-5: After a wake word triggers, the surface captures speech and determines the end of the
   utterance from a configurable trailing-silence period, bounded by a configurable maximum
   utterance length so capture cannot continue indefinitely.
6. FC-6: Captured speech is transcribed offline to text. The transcription model and its
   operating parameters are configuration; the defaults are those proven in the user's
   stenographer project: `Systran/faster-distil-whisper-medium.en`, `int8`, beam size 5,
   English.
7. FC-7: The resulting transcript is submitted to the engine as a turn through the established
   contract, attributed to this surface.
8. FC-8: While no speaking capability exists, the surface presents what it heard and what the
   engine answered as text on its own output, so it is usable and verifiable standalone.
9. FC-9: The surface presents the engine's tool activity and errors through the shared safety
   policy, never internal detail.
10. FC-10: The surface **retries with backoff** when the engine is unreachable, rather than
    exiting, so that it survives the engine starting later or restarting. This is a deliberate
    divergence from the chat surface's fail-fast behavior, justified by the voice surface being
    unattended.
11. FC-11: Audio input enters the pipeline through a seam that can be driven by supplied audio
    rather than a live device, so wake, endpointing, and transcription are provable without
    hardware and CI stays hermetic.
12. FC-12: The audio surface's configuration lives in its own file under the configuration
    directory, loaded by the shared configuration facility, holding only this surface's
    settings.
13. FC-13: The model registry's selection step no longer targets the engine's configuration,
    and fails with a clear, actionable message rather than an unhandled error when its target
    section is absent.
14. FC-14: Documentation reflects what actually exists: which wake models are trained versus
    which are configured-for-but-untrained, how the audio surface is run and configured, and
    how a newly-trained model is made active. The stale claim that the runtime takes a single
    shared wake threshold is corrected.
15. FC-15: **Capture is continuous and full-duplex-compatible.** Audio capture and wake
    detection run continuously and independently of turn state: the surface does not stop
    listening while a turn is in flight, and capture never blocks on the engine or on
    transcription. The input path must not assume exclusive access to the audio device, so that
    audio can be captured and played simultaneously. This plumage plays no audio itself, and
    this criterion asks for no playback — it exists because the speaking plumage requires the
    microphone to remain live *while* the assistant speaks, which a sequential
    listen-then-answer loop cannot support. Building the capture path duplex-compatible here
    is what allows the two halves of voice to be built in parallel rather than the second
    reworking the first.

## Acceptance Criteria

- [ ] AC-1: A test demonstrates that supplied audio containing a wake word activates the
      surface, and audio without one does not (FC-1, FC-11).
- [ ] AC-2: A test demonstrates that the active wake-model set is driven by configuration, that
      more than one model can be active at once with any of them triggering, and that the
      surface operates correctly with exactly one model configured (FC-2).
- [ ] AC-3: A test demonstrates each configured model's own threshold governing its own
      detection, with no global threshold (FC-3).
- [ ] AC-4: The registry's selection step writes each selected model's location and threshold
      into the audio surface's configuration; a test asserts the written values round-trip and
      match the registry (FC-4).
- [ ] AC-5: A test demonstrates utterance capture ending after the configured trailing-silence
      period, and a separate test demonstrates the maximum-utterance bound terminating capture
      when silence never arrives (FC-5).
- [ ] AC-6: A test demonstrates supplied speech audio transcribed to expected text, with the
      transcription model and parameters taken from configuration (FC-6).
- [ ] AC-7: A test demonstrates the transcript submitted to the engine as a turn attributed to
      this surface, and the engine's answer received back (FC-7).
- [ ] AC-8: A test demonstrates the heard transcript and the engine's answer presented on the
      surface's output (FC-8).
- [ ] AC-9: A test demonstrates the surface presenting tool activity and errors via the shared
      safety policy, with no internal detail reaching its output (FC-9).
- [ ] AC-10: A test demonstrates the surface retrying a failed connection with backoff instead
      of exiting, and succeeding once the engine becomes reachable (FC-10).
- [ ] AC-11: The full listening pipeline is exercised end to end from supplied audio to
      submitted turn without any audio hardware, and CI requires none (FC-11).
- [ ] AC-12: The audio surface reads only its own configuration file via the shared facility; a
      test asserts it loads independently of the engine's configuration (FC-12).
- [ ] AC-13: The registry's selection step targets the audio surface's configuration and emits
      a clear, actionable error when its target section is absent; a test covers the absent
      case (FC-13).
- [ ] AC-14: Documentation states which wake models are trained and which are not, documents
      running and configuring the audio surface and activating a newly-trained model, and no
      longer claims an untrained model exists or that a single shared threshold is used
      (FC-14).
- [ ] AC-15: A manual verification procedure covers live-microphone capture end to end, since
      real capture is the one part not provable hermetically (FC-11).
- [ ] AC-16: A test demonstrates capture and wake detection continuing uninterrupted while a
      turn is in flight — i.e. with the engine call outstanding, the surface is still consuming
      audio and still able to detect a wake word — proving the pipeline does not pause
      listening for the duration of a turn (FC-15).
- [ ] AC-17: A test demonstrates the capture path acquiring the input device in a manner that
      does not require exclusive access, so that simultaneous playback is possible (FC-15).
- [ ] AC-18: Every test in this plumage's feathers was written first and observed failing
      against the unchanged code for the expected reason before the implementation was
      corrected until it passed.
- [ ] AC-19: The full existing test suite passes.

## Out of Scope

- **Speaking.** Text-to-speech, playback, and voice output are the following plumage. This
  plumage's output is text.
- **Acoustic echo cancellation and barge-in.** Deliberately excluded: echo cancellation exists
  to stop the assistant's own speech from re-triggering its microphone, and that cannot happen
  until something speaks. It belongs with the speaking plumage or later. Its dependency already
  exists, deliberately excluded from the default install pending validation on the target
  device.
- **Training the second wake model.** Producing the Prometheus model needs specific GPU
  hardware and hours of wall-clock belonging to the user; an implementer can neither perform
  nor verify it. This plumage makes the model set data-driven so that training it later
  activates it with no code change. Until then the surface runs on the one trained model.
- **Changing the wake words or retraining the existing model.** Settled and complete
  separately; not revisited.
- **A combined voice-and-chat surface.** Intended later; the contract makes it possible.
- **Per-surface release binaries.** Unchanged from the platform plumage: still a separate
  packaging concern.
- **Streaming or partial transcription.** The engine's contract takes a final transcript per
  turn; incremental recognition is not required to satisfy this plumage and is not attempted.
- **Speaker identification, multi-user voice, or wake-word personalization.** Not asked for.

## Open Questions

- **The default transcription model is sized for a desktop, and hearth's stated primary target
  is a Raspberry Pi 5.** The inherited default (`Systran/faster-distil-whisper-medium.en`,
  roughly 800 MB, `int8`) is proven in the user's stenographer project, which runs on desktop
  hardware. On the Pi it may prove too slow or too large for comfortable conversational
  latency. This is deliberately **not** treated as a blocker: the model and its parameters are
  configuration (FC-6), which is exactly what allows the Pi to run a smaller model without a
  code change, consistent with the project's config-only Pi-port goal. Recorded so that if
  latency disappoints on the Pi, the first thing to reach for is known, and the finding is not
  mistaken for a defect in this plumage.
