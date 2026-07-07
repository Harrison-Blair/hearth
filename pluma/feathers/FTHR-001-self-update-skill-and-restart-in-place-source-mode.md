---
id: FTHR-001
title: Self-update skill and restart-in-place (source mode)
plumage: PLM-001
status: pipping
priority: P2
depends_on: []
oversight: merge
authored: 2026-07-07T02:56:55Z
agent: fledge-orchestrate/planning
fledge_version: 0.1.0
---

# FTHR-001: Self-update skill and restart-in-place (source mode)

## Description
The tracer-bullet slice for PLM-001: a complete, working self-update path in source
run mode, minus the TUI-supervision hardening (FTHR-002). Delivers three things that
compose into one vertical slice — voice/typed → intent → confirm → in-character
sign-off → restart-in-place that reloads on-disk code:

1. A **restart-in-place primitive**: a small, injectable callable that re-executes
   the daemon (`python -m assistant.app`) via `os.execv`, replacing the process image
   so a fresh interpreter loads whatever code is currently on disk. No network, no
   git, no install.
2. A **post-speak restart seam** on the pipeline: a declarative `SkillResult.restart`
   flag (mirroring the existing `expects_reply` flag) that the pipeline honors *after*
   it has finished speaking the reply — so the sign-off is actually heard before the
   process is replaced.
3. A new **`UpdateSkill`**: recognizes an update-self intent, asks for confirmation
   via the existing confirm-then-act reply round, and on an affirmative reply returns
   a quirky in-character Calcifer sign-off flagged to restart.

Satisfies PLM-001 FC-1..FC-7 for the source run mode. FC-7's "under the TUI, not
treated as a crash" is verified/hardened separately in FTHR-002.

## Affected Modules
- **`assistant/skills/` (new `update.py`)** — the `UpdateSkill`. See
  `.fledge/nest/entry-points.md` → "Skill contract" and `.fledge/nest/modules.md`
  → skills; model it on `StandDownSkill` (canned in-character replies) and
  `ReminderSkill.manage_reminders` (the `expects_reply` confirm-then-act precedent).
- **`assistant/core/events.py`** — add `SkillResult.restart: bool = False` beside the
  existing `expects_reply` flag (`.fledge/nest/data-model.md` → events).
- **`assistant/core/pipeline.py`** — honor `result.restart` after `await self._speak(...)`
  in the reply path (and, defensively, the direct path); take an injected
  `restart_in_place` callable in `__init__`. See `.fledge/nest/architecture.md` →
  "confirm-then-act reply seam" and the `_handle`/`_dispatch_reply` speak points.
- **`assistant/core/selfupdate.py` (new)** — the `restart_in_place()` primitive
  (`os.execv(sys.executable, [sys.executable, "-m", "assistant.app"])`), with stdio
  flush + a log line before exec. Source mode only (see PLM-001 Out of Scope: frozen
  binary is FTHR of a future plumage).
- **`assistant/app.py`** — construct the `restart_in_place` callable, inject it into
  `VoicePipeline`, construct and `registry.register(UpdateSkill(...))`. Composition
  root only, per `.fledge/nest/architecture.md` → "app.py is the only wiring point".
- **Tests** — `tests/test_update_skill.py`, `tests/test_selfupdate.py`, and new cases
  in `tests/test_pipeline.py` (`.fledge/nest/testing.md`).

## Approach
**Intent + skill.** `UpdateSkill` declares `name = "update"`, `intents = {"update_self"}`,
and a `tool_specs` entry describing "restart the assistant to load the latest code
already on disk" (no required slots). The orchestrator exposes it as a tool
automatically (`SkillRegistry.tool_schemas()`), so both the spoken path and the typed
`submit_text` path route to it with no routing special-casing.

**Confirm-then-act.** `handle()` returns `SkillResult(speech=<confirm prompt>,
expects_reply=True)` — it never restarts directly. The pipeline's existing one-round
reply seam dispatches the next utterance to `handle_reply(cmd)`. `handle_reply()`
treats an affirmative (same "confirm"/yes-style check the stand-down/reminder flows
use) as go, and anything else — including an empty/silent transcript — as cancel.
Per PLM-001's open question, the typed path also confirms in this feather (no
`spoken`-based shortcut); revisit only if the user asks.

**Sign-off, then restart — ordering is the crux.** The pipeline speaks
`result.speech` *after* the skill returns (`_handle`/`_dispatch_reply` both call
`await self._speak(...)` post-return). So the skill must NOT call `os.execv` itself —
that would kill the process before the sign-off is ever spoken. Instead `handle_reply`
returns `SkillResult(speech=<quirky Calcifer sign-off>, restart=True)`, and the
pipeline, only after `await self._speak(...)` has completed (audio finished), invokes
the injected `restart_in_place()`. This makes the sign-off audible and the restart a
declarative consequence, testable by a fake restart callback.

**Sign-off content.** A small set of canned, in-character Calcifer sign-off lines
(e.g. "Ugh, fine — dousing myself. Don't let the logs go cold.") chosen at reply
time, kept in the skill. Deliberately **not** an LLM/persona round: `persona.py` is a
prompt-tone layer for LLM final replies, and making an LLM call in the moment before
replacing the process is fragile and slow. Canned lines in Calcifer's established
voice honor the "quirky in-persona sign-off" intent without that dependency. (If the
user later wants generated variety, that's a follow-up feather.)

**Restart primitive.** `restart_in_place()` lives in its own module so it is trivially
mockable: it flushes stdio, logs, and calls `os.execv` with the source-mode target.
`VoicePipeline` receives it as a constructor dependency (default may be the real
primitive; tests inject a fake that records the call instead of exec'ing). The real
`os.execv` is never invoked in tests.

**No network.** Nothing in this path imports or calls network/git/subprocess — FC-6
holds by construction, asserted by the absence of such calls in the exercised units.

## Tests
Written test-first; each observed FAILING against unchanged code for the stated
reason, then made to pass.

- `test_update_command_prompts_confirmation` (skill) — `handle()` on an update
  command returns `expects_reply=True` with a confirmation prompt and `restart` false.
  Fails now: no `UpdateSkill`. (PLM-001 FC-1, FC-3)
- `test_typed_update_routes_to_update_self` (pipeline/orchestrator) — a typed
  update command routes to the `update_self` intent / `UpdateSkill`. Fails now: intent
  unknown. (FC-2)
- `test_confirm_returns_signoff_and_restart_flag` (skill) — `handle_reply()` with an
  affirmative reply returns a non-empty sign-off `speech` and `restart=True`. Fails
  now: no skill. (FC-4)
- `test_pipeline_invokes_restart_after_speaking` (pipeline) — given a reply result
  with `restart=True`, the pipeline calls the injected `restart_in_place` callable,
  and does so *after* `_speak` of the sign-off (ordering asserted, e.g. via an
  ordered record of speak/restart calls). Fails now: no `restart` field/hook. (FC-4)
- `test_decline_or_silence_cancels_no_restart` (skill + pipeline) — a negative,
  unrelated, or empty reply yields `restart=False` and the injected restart callable
  is never called. Fails now: no skill/hook. (FC-5)
- `test_restart_in_place_reexecs_source_target` (selfupdate) — with `os.execv`
  monkeypatched to capture, `restart_in_place()` calls it once with
  `[sys.executable, "-m", "assistant.app"]` and makes no network/subprocess call.
  Fails now: module doesn't exist. (FC-6, FC-7 standalone)

## Acceptance Criteria
- [x] AC-1: The tests listed above were observed failing before implementation and pass after.
- [x] AC-2: A spoken update command (and at least one paraphrase) and the same command
      typed both route to the `update_self` intent and produce a confirmation prompt
      (`expects_reply=True`), not an immediate restart. (PLM-001 FC-1, FC-2, FC-3)
- [x] AC-3: An affirmative confirmation yields a non-empty in-character sign-off and
      causes the pipeline to invoke the injected restart callable, strictly after the
      sign-off has been spoken. (PLM-001 FC-4)
- [x] AC-4: A negative, unrelated, or silent confirmation reply performs no restart
      (injected callable never called) and returns the assistant to normal listening.
      (PLM-001 FC-5)
- [x] AC-5: `restart_in_place()` re-execs the source-mode target
      `[sys.executable, "-m", "assistant.app"]` and the exercised path makes no
      network, git, or subprocess call. (PLM-001 FC-6, FC-7 standalone)
- [x] AC-6: The restart mechanism is injected into `VoicePipeline` (not hard-wired),
      and `os.execv` is never called during the test suite. (testability seam)
- [x] AC-7: `pytest` is green and `ruff check assistant tests` is clean.
