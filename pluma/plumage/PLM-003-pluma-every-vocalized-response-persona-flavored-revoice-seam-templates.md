---
id: PLM-003
title: "Pluma: every vocalized response persona-flavored (revoice seam + templates)"
status: hatched
priority: P1
authored: 2026-07-07T17:52:04Z
agent: fledge-orchestrate/planning
fledge_version: 0.2.0
---

# PLM-003: Pluma: every vocalized response persona-flavored (revoice seam + templates)

## Context
The Calcifer persona today is a tone layer appended only to final-reply LLM
prompts (`core/persona.py`): GeneralSkill answers, WeatherSkill, WebSearchSkill
summaries, and verify's spoken feedback/rewrites carry the voice. Everything
else reaching TTS is plain canned text — ClockSkill time/date strings,
ReminderSkill confirmations, CalendarSkill confirmations/listings, TimerSkill,
StandDownSkill, the ReminderScheduler's fired/catch-up announcements, the
CalendarWatcher's event announcements, UpdateSkill's pre-restart lines, the
LLM-offline/failure messages, and the pipeline's generic error strings. The
persona is a convention, not a guarantee: nothing stops a new skill or a bare
`_speak("...")` from shipping unflavored speech.

This plumage makes "every vocalized response is flavored" a structural
invariant, via a hybrid: a **revoice seam** — one choke point at the speak
boundary that passes not-yet-voiced text through a persona-bearing LLM call
("restyle, never re-answer, keep numbers byte-exact") — and **persona
templates** for paths that cannot reach the LLM (UpdateSkill speaks
immediately before the process re-execs; offline/failure messages fire when
the model is down). A `Revoicer` is constructed in `app.py` (the composition
root) and injected into the pipeline, reminder scheduler, and calendar
watcher; `SkillResult` gains a `voiced` flag (default `False`) so
already-persona'd LLM output passes through untouched and new skills are
flavored automatically.

The persona doc's v1 rule "routine or deterministic commands: drop the
theatrics, just confirm" is rewritten in v2: deterministic replies carry the
character too (brief, but in voice). Per the module's own convention, the
versioned blocks bump `_CALCIFER_V1_*` → `_CALCIFER_V2_*`.

Offline-first is preserved: revoice is an accelerator, never a dependency. A
known-down LLM short-circuits straight to plain speech; a slow or failed
revoice falls back to the plain string after a bounded timeout; and a
deterministic digit-preservation guard converts the worst failure mode
(a garbled time from the *clock*) into a graceful unflavored reply.

## User Stories
- As a voice user, I want every reply — "what time is it", reminder
  confirmations, calendar announcements, even error messages — to sound like
  Calcifer, so the assistant is one consistent character rather than a
  character that flickers on and off per skill.
- As the operator, I want revoicing to never block or break speech: if the
  LLM is down, slow, or garbles a number, I hear the plain accurate reply
  instead of silence or a wrong time.
- As the operator, I want independent levers — persona off entirely, or
  persona on but live revoice off (`revoice_enabled`) — so I can rein in the
  added latency without losing the character everywhere.
- As a future contributor, I want the invariant enforced by tests, so a new
  skill or a bare `_speak()` call can't silently ship unflavored speech.

## Functional Criteria
Numbered, testable statements of behavior. Referenced downstream as FC-1, FC-2, …
1. FC-1: `core/persona.py` bumps to v2: the "drop the theatrics" rule is
   replaced with in-character-but-brief guidance for deterministic replies;
   versioned block names change so replay captures/evals key on the new text.
2. FC-2: A `Revoicer` component performs the live re-voice: prompt = persona
   block + the plain string only (no user command, no conversation history),
   instructed to restyle without re-answering and to keep every time, date,
   and number byte-exact. It reuses the orchestrator's `LLMProvider`
   instance, injected from `app.py`.
3. FC-3: `SkillResult` (`core/events.py`) gains `voiced: bool = False`.
   GeneralSkill, WeatherSkill, WebSearchSkill, and verify's
   `rewritten_speech` path mark their results `voiced=True`; deterministic
   skills are untouched and default to `False`.
4. FC-4: The speak boundary is the only flavoring choke point: text reaching
   TTS in `pipeline._speak`, the ReminderScheduler (fired reminders and the
   catch-up summary, revoiced as one call), and the CalendarWatcher is
   revoiced when persona is enabled, `revoice_enabled` is true, and the text
   is not already voiced.
5. FC-5: Failure semantics: if the provider is known unhealthy, revoice is
   skipped immediately (no added dead air); otherwise the call is bounded by
   `persona.revoice_timeout_s` (default 5.0). Timeout, error, or empty output
   → the plain string is spoken and a warning logged. Speech is never lost.
6. FC-6: Digit-preservation guard: every digit sequence present in the plain
   string must appear verbatim in the revoiced text; any miss → the plain
   string is spoken. Name/word paraphrase is acceptable drift.
7. FC-7: LLM-free paths use persona templates via a `canned(key)` lookup in
   `core/persona.py` with 2–3 rotated variants per message (injectable/
   seedable rotation for deterministic tests): UpdateSkill's pre-restart
   lines, GeneralSkill's LLM-offline/no-answer messages, the pipeline's
   "something went wrong" / "can't help with that yet" strings, and
   `skills/base.py`'s unexpected-reply fallback. Persona disabled → the
   current plain strings, byte-identical.
8. FC-8: New typed fields on `PersonaConfig`: `revoice_enabled: bool = True`,
   `revoice_timeout_s: float = 5.0`, mirrored in `config.yaml` and
   `default-config.yaml`. `persona.enabled = false` keeps every path plain
   and skips all new work; `revoice_enabled = false` keeps persona on LLM
   prompts and templates but performs no live revoice calls.
9. FC-9: Hardening tests: (a) the orchestrator's tool-decision prompt
   contains no persona text even with persona enabled (persona never touches
   routing/JSON calls); (b) a pipeline-level spy-TTS invariant test proves
   that with persona enabled, no unflavored text reaches TTS — everything is
   voiced, revoiced, or a persona template.

## Acceptance Criteria
Checkbox list of verifiable conditions under which this plumage is considered fledged, one `- [ ] AC-N: …` line each. Authored unchecked; checked only via `fledge criteria check` at plumage closeout.
- [ ] AC-1: With persona enabled, a deterministic skill reply (e.g. clock)
      is revoiced before TTS — output differs in style from the plain string
      while every digit sequence survives verbatim; with persona disabled the
      spoken text is byte-identical to today's.
- [ ] AC-2: ReminderScheduler announcements (single, and the catch-up
      summary as one call) and CalendarWatcher announcements pass through the
      same revoice seam.
- [ ] AC-3: A known-unhealthy provider short-circuits to plain speech with
      no timeout delay; a hung or failing revoice call falls back to the
      plain string after `revoice_timeout_s` with a logged warning — in no
      case is a reply dropped.
- [ ] AC-4: A revoiced output that drops or mutates any digit sequence is
      discarded and the plain string is spoken (guard test with a stub LLM
      returning garbled numbers).
- [ ] AC-5: UpdateSkill, LLM-offline, pipeline-error, and base-fallback paths
      speak a Calcifer template variant when persona is enabled (rotation
      deterministic under an injected seed) and the current plain string when
      disabled.
- [ ] AC-6: `revoice_enabled: false` with persona on: LLM-generated replies
      and templates stay flavored, deterministic skill replies are spoken
      plain, and no revoice LLM call is made.
- [ ] AC-7: Hardening tests pass: tool-decision prompt is persona-free with
      persona enabled, and the spy-TTS invariant test fails if an unflavored
      string is fed to `_speak` without passing the seam.
- [ ] AC-8: The full test suite passes without native extras or network
      (LLM stubbed per repo convention), and `ruff check assistant tests` is
      clean.

## Out of Scope
- Revoice seeing the user's command or conversation history.
- A separate/dedicated revoice model or model config.
- LLM-verify pass over revoiced text (the digit guard is the only check).
- Name/entity preservation guarding (paraphrase accepted).
- Flavoring non-TTS surfaces: earcons, TUI text, logs.
- Template rotation beyond 2–3 variants, or persisted rotation state.
- Any change to routing/tool-decision behavior — persona stays off those
  prompts, now enforced by test.

## Open Questions
- Exact v2 wording of the Calcifer blocks and the template variants —
  authored at feather level, gated with the feather drafts.
