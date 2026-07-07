---
id: FTHR-007
title: "Template adoption: LLM-free call sites speak canned() persona lines"
plumage: PLM-003
status: egg
priority: P1
depends_on: [FTHR-005, FTHR-006]
authored: 2026-07-07T19:23:41Z
agent: fledge-orchestrate/planning
fledge_version: 0.2.0
---

# FTHR-007: Template adoption: LLM-free call sites speak canned() persona lines

## Description
Widens the tracer slice: every LLM-free spoken line swaps its literal for the
FTHR-006 `canned()` registry, and is marked voiced so the FTHR-005 seam never
tries to revoice a template (an `llm_offline` line must not trigger a call to
the very model that just failed). After this feather, all persona-template
paths from PLM-003 FC-7 are live:

- `pipeline.py` — the two "Sorry, something went wrong." sites →
  `canned("error_generic")`, "Sorry, I can't help with that yet." →
  `canned("cant_help")`, each passed to `_speak(..., voiced=True)`.
- `skills/general.py` — LLM-offline and no-answer failures →
  `canned("llm_offline")` / `canned("no_answer")`, returned
  `voiced=True` (the success path already carries persona via FTHR-005).
- `skills/base.py` — the unexpected-reply fallback →
  `canned("unexpected_reply")`, `voiced=True`.
- `skills/update.py` — the local `_SIGNOFFS` tuple and `random.choice` are
  replaced by `canned("update_signoff")`, `voiced=True`; the lines
  themselves moved to the registry in FTHR-006.

Persona disabled keeps every one of these byte-identical to today (pinned by
FTHR-006's fallback tests plus the call-site tests here).

Satisfies PLM-003 FC-7 (call-site half); completes AC-5.

## Affected Modules
- **`assistant/core/pipeline.py`** — error-string sites (owned by FTHR-005's
  merged seam; this feather only swaps the literals and adds `voiced=True`).
- **`assistant/skills/general.py`** — failure messages.
- **`assistant/skills/base.py`** — `unexpected-reply` fallback.
- **`assistant/skills/update.py`** — sign-off via registry; drop `_SIGNOFFS`
  and the local `random` use.
- **`assistant/app.py`** — only if call sites need the persona-enabled flag
  threaded (prefer passing `enabled` where each component is constructed).

## Approach
Test-first. Mechanical swaps only — no new behavior beyond flavor:
each site calls `canned(key, enabled=...)` at speak/return time (not at
construction), so a persona toggle needs no object rebuilds beyond what
exists. The persona-enabled flag reaches skills the same way
`persona_suffix` already does (constructor arg from `app.py`). No new
config. UpdateSkill keeps its "deliberately no LLM call before re-exec"
property — `canned()` is pure lookup.

## Tests
- Extended `tests/test_pipeline.py`: with persona enabled, the error and
  can't-help paths feed a Calcifer variant to TTS marked voiced (spy TTS +
  spy Revoicer: zero revoice calls); disabled → the exact current literals.
- Extended `tests/test_general_skill.py`: offline/no-answer results carry a
  registry variant and `voiced=True`; disabled → current strings.
- Extended `tests/test_update_skill.py`: sign-off comes from the registry
  (seeded rng → deterministic variant), `voiced=True`, still `restart=True`
  and no LLM call.
- New case for `skills/base.py`'s fallback via any registered skill stub.

Implementation order is fixed: (1) write the tests; (2) confirm they FAIL
against unchanged code for the expected reason; (3) implement until they
pass.

## Acceptance Criteria
- [ ] AC-1: The tests listed above were observed failing before
      implementation and pass after.
- [ ] AC-2: All FC-7 call sites speak registry variants when persona is
      enabled and the exact current literals when disabled (PLM-003 AC-5).
- [ ] AC-3: Template lines never enter the revoice path — each is voiced at
      its source; a spy Revoicer records zero calls for them.
- [ ] AC-4: No literal spoken string for these messages remains outside
      `persona.py` (grep-clean), and `ruff check assistant tests` plus the
      full suite pass.
