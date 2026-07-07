---
id: FTHR-009
title: "Hardening invariants: spy-TTS flavor guarantee + persona-free routing"
plumage: PLM-003
status: egg
priority: P1
depends_on: [FTHR-007, FTHR-008]
authored: 2026-07-07T19:25:50Z
agent: fledge-orchestrate/planning
fledge_version: 0.2.0
---

# FTHR-009: Hardening invariants: spy-TTS flavor guarantee + persona-free routing

## Description
Test-only closeout feather turning PLM-003's guarantee from "implemented"
into "enforced". Two invariants, each written to fail loudly when a future
change violates it:

1. **Nothing unflavored reaches TTS** (PLM-003 FC-9b). A pipeline-level test
   with a spy TTS and a tagging stub Revoicer (its output carries a marker)
   drives every speech path — deterministic skill result, persona-marked LLM
   skill result, verify feedback via `on_say`, pipeline error/can't-help
   paths — and asserts every string the TTS receives is either
   revoicer-tagged, produced under `voiced=True`, or a `canned()` registry
   variant. Because `_speak` defaults to `voiced=False`, any future bare
   `_speak("...")` literal lands in the revoicer (flavored automatically) —
   the test additionally pins that default.
2. **Persona never touches routing** (PLM-003 FC-9a). With persona enabled
   and a capturing stub LLM, the orchestrator's tool-decision request
   (system + messages + tool schemas) contains no substring of the v2
   persona blocks; same assertion for the verify `decision` context. Guards
   the invariant documented in `persona.py`/`verify.py` docstrings.

Satisfies PLM-003 FC-9; completes AC-7.

## Affected Modules
- **`tests/test_pipeline.py`** (or a new `tests/test_speech_invariants.py`
  if the fixtures outgrow it) — invariant 1.
- **`tests/test_orchestrator.py` / `tests/test_orchestrator_verify.py`** —
  invariant 2.
- No production code. If a seam is missing for observability, that is a
  finding to fix in the owning feather's module, not here — flag it rather
  than patching around it.

## Approach
Reuse the stub/spy fixtures established by FTHR-005/007/008. Assert against
the persona v2 block *content* imported from `persona.py` (not copied
strings), so future persona v3 text keeps the routing test honest without
edits. Keep invariant 1's path list explicit and commented as the
maintenance point for future speech paths.

## Tests
As described above — the tests are the deliverable:
- spy-TTS flavor invariant across all four path classes
- `_speak` default-unvoiced pin
- tool-decision request persona-free (native and JSON tool modes)
- verify decision-context persona-free (feedback/rewrite fields exempt)

Verification discipline for a test-only feather: each new test must be
demonstrated to FAIL under a deliberate seam break (e.g. bypass the revoicer
in `_speak`, or append the persona suffix to the tool-decision system
prompt), then pass with the break reverted — evidence captured in the molt
file per AC-2.

## Acceptance Criteria
- [x] AC-1: All new invariant tests pass on the completed PLM-003 stack.
- [x] AC-2: Each invariant test was observed failing under a deliberate
      seam break (documented break → failure → revert → pass), proving it
      guards the behavior (PLM-003 AC-7).
- [x] AC-3: No production file is modified by this feather.
- [x] AC-4: `ruff check assistant tests` and the full suite pass without
      native extras or network (closes PLM-003 AC-8).
