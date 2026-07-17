---
id: PLM-007
title: "Veneer platform: standalone chat veneer and the veneer-engine contract"
status: fledged
priority: P0
authored: 2026-07-17T07:19:49Z
agent: fledge-orchestrate/planning
fledge_version: 0.6.7
---

# PLM-007: Veneer platform: standalone chat veneer and the veneer-engine contract

## Context

hearth is meant to become a voice assistant, but today it has exactly one user surface: a
localhost WebSocket control channel and a stdin/stdout console program that connects to it.
That console program is, in practice, the only thing a human touches — yet it is treated as a
trivial dev/test client rather than a first-class part of the product, and it reads its
connection settings out of the engine's own configuration.

The user wants voice added as a **new, separate surface**, and wants a hard line between the
engine (the "brain": routing, orchestration, memory, tools) and the surfaces a person
interacts with — each surface "only handling the routing of the inputs and the final
display/user interaction."

Much of that separation already exists in substance: the surface layer never reaches into the
engine's internals, it reaches the engine only through a single turn-processing entry point,
and what may cross to a client is governed by a structural whitelist with a test asserting
that tool internals never leak. What does **not** exist is the *platform*: the vocabulary,
the contract, and the packaging that let more than one surface exist at all. Everything is
shaped around there being exactly one, and — critically — the codebase uses "veneer" to mean
the engine-side channel, while the user uses it to mean the user-facing program. That
ambiguity is not cosmetic: it actively misleads readers of the code about which side of the
boundary a component belongs to.

This plumage establishes that platform and settles the vocabulary. It is the **tracer bullet**
for the voice work: it proves the architecture end to end with a real surface, over the real
wire, under the real safety boundary, before any audio exists. The two audio plumages that
follow (listening path; speaking path) are then implementations of the contract this plumage
defines, and can proceed in parallel.

It deliberately ships **no new user-facing capability**. Its value is that after it lands, a
second surface is a straightforward addition rather than an architectural question — and the
existing one is a real, named, separately-configured program.

## User Stories

- As the assistant's user, I want the program I talk to hearth through to be a first-class,
  separately-runnable thing called `chat`, so that it is a real surface I can run, configure,
  and reason about — not an incidental test client.
- As the assistant's user, I want each surface and the engine to have their own configuration,
  so that changing how I reach hearth over voice never risks disturbing how the engine
  itself runs, and I can see at a glance which settings belong to what.
- As the assistant's user, I want to run more than one surface against a single engine at the
  same time on one device, so that (for example) a voice surface and a chat window can both be
  live without one interfering with the other.
- As the assistant's user, I want a surface that cannot reach the engine to tell me so plainly,
  so that a stopped daemon is an obvious, self-explaining condition rather than a stack trace.
- As a developer adding a new surface, I want one contract that says what a surface must do
  and one place that decides what is safe to show a person, so that I can build the audio
  surface without re-deriving the boundary or re-implementing its safety rules.
- As a developer reading the code, I want "veneer" to mean exactly one thing — the user-facing
  program — so that the name stops misleading me about which side of the engine boundary a
  component sits on.

## Functional Criteria

1. FC-1: A veneer is a **separate process** from the engine. It reaches the engine only over
   the engine's local wire, and never by in-process access to the engine's internals. The
   process boundary is the separation between brain and user surface.
2. FC-2: The engine exposes a single gateway for veneers to connect to. The gateway's naming
   is unambiguously engine-side, distinct from the veneers themselves; the word "veneer" refers
   only to the user-facing programs.
3. FC-3: The existing stdin/stdout console surface is promoted to a first-class veneer named
   **`chat`**, separately runnable by name, with behavior equivalent to today's client.
4. FC-4: Every user-facing surface obtains its notion of what is safe to show a person from a
   **single shared source of that policy**. No surface may present internal failure detail or
   tool internals; a surface must not be able to satisfy this by re-implementing the rules
   itself.
5. FC-5: Multiple veneers may be connected to one engine concurrently on a single device, each
   served independently.
6. FC-6: Concurrent veneers hold **separate, isolated conversations**. A turn taken on one
   surface does not enter another surface's conversation history.
7. FC-7: The engine does not serialize turns across veneers; concurrent turns from different
   surfaces are each served.
8. FC-8: Each turn recorded in the engine's durable log is attributable to the surface it came
   from, so a spoken turn can be distinguished from a typed one after the fact.
9. FC-9: Configuration is **per component**: the engine and each veneer each read only their
   own configuration file, organized under a single configuration directory. No component's
   configuration file contains another's settings.
10. FC-10: The configuration-loading mechanism is **shared**, not duplicated per component:
    one parameterized facility provides path resolution, the documented-reference/active-file
    pattern, environment-variable overrides, and fail-loud behavior on missing configuration,
    for the engine and every veneer alike.
11. FC-11: The engine's configuration no longer carries surface connection settings; those
    belong to the surface that uses them.
12. FC-12: The previous single-surface configuration naming is removed outright, with no
    backward-compatibility shim.
13. FC-13: A veneer that cannot reach the engine reports that plainly — identifying the engine
    it tried to reach and that the engine may not be running — and exits non-zero, without a
    stack trace.
14. FC-14: The engine's release binary continues to build and to locate its configuration, both
    from a source checkout and when frozen, after the configuration reorganization.
15. FC-15: Project documentation reflects the settled vocabulary and the new way to run each
    component; no documentation describes the superseded single-surface arrangement.

## Acceptance Criteria

- [x] AC-1: A veneer runs as its own process and reaches the engine only over the wire; the
      `chat` veneer holds no in-process reference to engine internals (FC-1).
- [x] AC-2: The engine-side gateway is named distinctly from the veneers, and no engine-side
      component is named "veneer" (FC-2).
- [x] AC-3: The `chat` veneer is separately runnable by name and reproduces today's console
      behavior — prompt, turn submission, tool-activity display, answer display, error display
      (FC-3).
- [x] AC-4: Safety policy lives in one shared place that every surface goes through; a test
      demonstrates that a surface cannot present internal failure detail or tool internals, and
      that test is written so it applies to **any** surface rather than one specific one
      (FC-4).
- [x] AC-5: A test demonstrates two veneers connected to one engine concurrently, both served
      (FC-5).
- [x] AC-6: A test demonstrates that a turn on one concurrently-connected veneer does not
      appear in another's conversation history (FC-6).
- [x] AC-7: A test demonstrates concurrent turns from two surfaces each being served, with no
      engine-side serialization (FC-7).
- [x] AC-8: Each logged turn records its originating surface, and a test asserts turns from
      different surfaces are distinguishable in the log (FC-8).
- [x] AC-9: The engine and the `chat` veneer each read only their own configuration file from
      the configuration directory; a test asserts each component's configuration is loaded
      independently of the other's (FC-9, FC-11).
- [x] AC-10: Configuration loading is provided by one shared facility used by both the engine
      and the `chat` veneer; a test covers that facility's resolution order and its fail-loud
      behavior on missing configuration (FC-10).
- [x] AC-11: The superseded single-surface configuration section and its environment-variable
      names are gone from the codebase, with no compatibility alias (FC-12).
- [x] AC-12: A test demonstrates that a veneer started against an unreachable engine reports a
      plain, identifying message and exits non-zero without a stack trace (FC-13).
- [x] AC-13: The engine's release binary builds and resolves its configuration after the
      reorganization; the existing release smoke check passes unchanged in intent (FC-14).
- [x] AC-14: Documentation describes the engine, the `chat` veneer, how each is run and
      configured, and the settled vocabulary; no superseded single-surface description remains
      in project documentation (FC-15).
- [x] AC-15: Every test in this plumage's feathers was written first and observed failing
      against the unchanged code for the expected reason before the implementation was
      corrected until it passed.
- [x] AC-16: The full existing test suite passes.

## Out of Scope

- **The audio surface itself** — wake word, voice activity detection, speech-to-text,
  text-to-speech. This plumage builds the platform they plug into; they are the following two
  plumages.
- **Any new audio configuration.** The configuration directory gains a veneer's file here;
  audio's own configuration arrives with the audio plumages, where its settings actually
  exist.
- **Reconnection or retry when the engine is unreachable.** Deliberately deferred: a surface
  fails fast and plainly here. Retry is a genuine need for an always-on voice surface that may
  start before the engine on a constrained device — it belongs to the audio plumages, where
  that boot-ordering problem first exists, and where it can be built against a real case
  rather than an imagined one.
- **A release binary per veneer.** The engine's binary must keep working (FC-14), but shipping
  separate per-surface release artifacts is its own packaging concern and would delay the
  tracer bullet behind it.
- **A combined surface** offering both voice and chat at once. The user intends one later; this
  plumage makes it possible by settling the contract, and deliberately does not attempt it.
- **Engine-side turn queuing or concurrency limits.** Explicitly rejected for now (FC-7): the
  local model backend already manages its own request concurrency and knows more about its
  resources than hearth does. Revisit only if constrained hardware demonstrably thrashes —
  not before.
- **Sharing conversation state across surfaces.** Explicitly decided against (FC-6). Isolated
  conversations are today's behavior and remain so.
- **`training/`'s model-selection step.** It writes wake-word settings into the engine's
  configuration file by a hardcoded path, so the configuration reorganization makes that path
  stale. It is deliberately left alone: under this architecture wake-word settings are
  *audio-surface* configuration, so the correct target for that write does not exist until the
  audio plumage — fixing it here would aim it at the wrong file and require moving it again.
  See Open Questions for a defect found in it during interrogation.
- **The persona.** Settled separately and already fledged; untouched here.

## Open Questions

- **Pre-existing defect in `training/`'s model-selection step, found during interrogation and
  deliberately not fixed here.** That step — the documented final action of the wake-word
  training workflow — locates a wake-word section in the engine's configuration file with a
  lookup that has no fallback, and today's configuration file contains no such section (the
  engine's schema has never modelled one). It therefore fails with an unhandled iteration
  error if run as documented, **independently of this plumage** — this is not a regression
  introduced here. It is recorded so it is not mistaken for fallout from the configuration
  reorganization. The audio-listening plumage should own the fix, since that is where
  wake-word configuration is designed and where the write's correct destination first exists.
  Until then, the wake-word training workflow's final documented step does not run.
