---
id: PLM-001
title: "Self-update: restart in place to apply on-disk changes"
status: fledged
priority: P2
authored: 2026-07-07T02:54:03Z
agent: fledge-orchestrate/planning
fledge_version: 0.1.0
---

# PLM-001: Self-update: restart in place to apply on-disk changes

## Context
During development, applying a code change to the running assistant means stopping
the daemon and starting it again — a context switch away from the conversation, and
on the Raspberry Pi deployment it means reaching for a keyboard the device is not
meant to need. The assistant is voice-first and touch-only by design, so the person
using it should be able to tell Calcifer to pick up the latest code the same way
they ask it anything else: out loud.

This plumage adds a spoken (and typed) "update yourself" capability. It applies
only the code **already present on disk** — there is no network fetch, no pull from
a remote, no package install. The single effect is to restart the assistant in
place so a fresh process loads whatever code is currently on disk. Because a restart
is disruptive (it drops all in-memory state and briefly takes the assistant
offline), the command is confirmed before it acts, and Calcifer signs off in
character before going down — turning an abrupt restart into a deliberate, in-persona
goodbye-and-back-again.

It fits the existing product seams cleanly: confirmation reuses the assistant's
established confirm-then-act reply exchange, the sign-off rides the existing Calcifer
persona layer, and "restart clears in-memory state" is already the accepted behavior
for stand-down and reminders today.

## User Stories
- As a developer iterating on the assistant, I want to tell Calcifer to update
  itself after I change the code, so that my edits take effect without stopping and
  restarting the daemon by hand.
- As the person operating the touch-only Pi, I want to trigger the update by voice,
  so that I never need a keyboard to apply a change that is already on the device.
- As a cautious user, I want the assistant to confirm before it restarts, so that a
  misheard word can't knock it offline unexpectedly.
- As someone who enjoys Calcifer's character, I want a quirky in-persona sign-off
  before it goes down, so that the restart feels intentional and I know it's coming
  back.

## Functional Criteria
Numbered, testable statements of behavior. Referenced downstream as FC-1, FC-2, …
1. FC-1: A spoken request to update/restart-to-apply-changes (e.g. "update
   yourself", "restart with the new code", "apply the latest changes") is recognized
   as an update-self intent, distinct from stand-down, reminders, and general chat.
2. FC-2: The same request typed into the monitor's chat is recognized as the same
   update-self intent.
3. FC-3: On recognizing the intent, the assistant does **not** restart immediately;
   it first asks the user to confirm, in a single follow-up exchange that needs no
   new wake word.
4. FC-4: An affirmative confirmation causes the assistant to (a) speak a quirky,
   in-character Calcifer sign-off, then (b) restart itself in place so a fresh
   process loads the code currently on disk.
5. FC-5: A negative confirmation, an unrecognized reply, or silence cancels the
   update: no sign-off, no restart, and the assistant returns to normal listening.
6. FC-6: The update applies only code already on disk — the flow performs no network
   access, no version-control fetch, and no dependency installation.
7. FC-7: After the restart, the assistant comes back listening on the same voice and
   control surfaces it had before, with no manual intervention, in both supported run
   modes: standalone (`python -m assistant.app`) and under the monitor TUI's daemon
   supervision. Under the TUI, the supervisor does not report the transition as a
   crash/stopped daemon.
8. FC-8: The restart drops all in-memory runtime state (e.g. an active stand-down, a
   pending confirmation) — consistent with the assistant's existing "a restart clears
   this" behavior — and does not corrupt any on-disk state (the reminder/calendar
   stores survive intact).

## Acceptance Criteria
Checkbox list of verifiable conditions under which this plumage is considered fledged, one `- [ ] AC-N: …` line each. Authored unchecked; checked only via `fledge criteria check` at plumage closeout.
- [x] AC-1: A spoken "update yourself" (and at least one paraphrase, e.g. "restart
      with the new code") routes to the update-self intent and produces a spoken
      confirmation prompt rather than an immediate restart.
- [x] AC-2: The same command typed into the monitor chat routes to the update-self
      intent.
- [x] AC-3: Confirming the prompt produces an in-character sign-off utterance and
      then triggers a restart-in-place; the freshly started process is running the
      code as it exists on disk at restart time.
- [x] AC-4: Declining, replying with something unrelated, or staying silent cancels:
      no restart occurs and the assistant resumes normal listening.
- [x] AC-5: The update flow makes no network, git, or package-install calls (verified
      by the absence of such effects in the exercised path).
- [x] AC-6: Under the monitor TUI, a confirmed update restarts the daemon without the
      TUI treating it as a crash, and the assistant is responsive again afterward.
- [x] AC-7: Standalone (no TUI), a confirmed update restarts the process in place and
      it resumes listening without manual relaunch.
- [x] AC-8: On-disk stores (reminders, calendar state) are intact after an update
      restart.

## Out of Scope
- Fetching code from anywhere: no `git pull`, no download, no remote/cloud sync, no
  dependency (re)install. The feature only restarts to load what is already on disk.
- Frozen PyInstaller-binary deployment: only the source run mode
  (`python -m assistant.app`) is covered now. Re-applying an update on the frozen
  binary (different restart target, bundle chdir/env) is a future plumage.
- Any pre-flight validation of the on-disk code (syntax/import check, health probe,
  automatic rollback). If the code on disk is broken, recovery is manual for now.
- Preserving in-memory state across the restart (in-flight conversation, active
  stand-down, tap-to-listen). State loss is accepted, matching existing behavior.
- Updating the monitor TUI itself, or coordinating a combined daemon+TUI update.
- Scheduling, deferring, or auto-triggering updates (e.g. "update when idle",
  "check for updates"). The trigger is an explicit user command only.

## Open Questions
- Should the typed (monitor-chat) path also require the confirmation exchange, or
  apply immediately given that typing carries no mishearing risk (the precedent set
  by the stand-down/mute skill)? Deferred to feather-level design; default assumption
  is that both paths confirm, but this may be revisited.
- Whether a broken-code restart under the TUI should surface a distinct "update
  failed / daemon down after update" indication to the operator, versus the generic
  stopped-daemon state. Out of scope to build now, but flagged for the safety
  follow-up plumage.
