---
id: FTHR-006
title: "Persona v2 + canned() template registry"
plumage: PLM-003
status: pipping
priority: P1
depends_on: []
oversight: merge
authored: 2026-07-07T17:58:50Z
agent: fledge-orchestrate/planning
fledge_version: 0.2.0
---

# FTHR-006: Persona v2 + canned() template registry

## Description
The character-content half of PLM-003, confined to `core/persona.py` and its
tests so it runs in parallel with the FTHR-005 tracer. Two deliverables:

1. **Persona v2.** The v1 rule "Routine or deterministic commands: drop the
   theatrics, just confirm" is replaced with in-character-but-brief guidance
   (deterministic replies carry the voice — one flavored beat, then the
   fact). Both variants bump `_CALCIFER_V1_*` → `_CALCIFER_V2_*` per the
   module's versioned-block convention, so replay captures/evals key on the
   new text.
2. **`canned()` template registry.** A lookup for LLM-free spoken lines,
   2–3 Calcifer variants per key with injectable/seedable rotation
   (deterministic under a supplied `random.Random`), returning the current
   plain string when persona is disabled. Keys and their plain fallbacks:
   - `error_generic` — "Sorry, something went wrong."
   - `cant_help` — "Sorry, I can't help with that yet."
   - `llm_offline` — "Sorry, I couldn't reach my language model."
   - `no_answer` — "Sorry, I don't have an answer for that."
   - `unexpected_reply` — "Sorry, I wasn't expecting a reply."
   - `update_signoff` — migrates UpdateSkill's existing `_SIGNOFFS` lines
     (registry entries only here; the `update.py` call-site swap is FTHR-007).

This feather writes creative voice content — the v2 character blocks and
every template variant — hence `oversight: merge`: the user signs off on the
lines before they merge. Call sites are untouched (FTHR-007).

Satisfies PLM-003 FC-1 and the registry half of FC-7.

## Affected Modules
- **`assistant/core/persona.py`** — v2 blocks, `canned(key, *, enabled,
  rng=None)` registry. No other production file changes.
- **`tests/test_persona.py`** — extended for v2 and the registry.

## Approach
Test-first. Keep the module dependency-free (stdlib only), as today.
`canned()` with `enabled=False` returns the plain fallback byte-identical to
the current literals (pinned by test so FTHR-007's swaps are provably
behavior-preserving when persona is off). Unknown key → KeyError (call sites
own their keys; a typo should fail loudly in tests, not speak a wrong line).
Variant text follows the v2 rules: 1–2 sentences, no stage directions,
facts/numbers untouched (these lines contain none).

## Tests
Extended `tests/test_persona.py`:
- `persona_segment`/`suffix` return v2 text; the v1 "drop the theatrics"
  rule is gone; strength fallback (unknown → terse) still holds
- `canned(key, enabled=False)` returns the exact current plain string for
  every key
- `canned(key, enabled=True)` returns one of that key's 2–3 variants;
  rotation is deterministic under a seeded `random.Random` and covers all
  variants across draws
- unknown key raises KeyError

Implementation order is fixed: (1) write the tests; (2) confirm they FAIL
against unchanged code for the expected reason; (3) implement until they
pass.

## Acceptance Criteria
- [x] AC-1: The tests listed above were observed failing before
      implementation and pass after.
- [x] AC-2: v2 blocks replace v1 with the deterministic-replies-in-voice
      guidance; no `_CALCIFER_V1_*` name survives (PLM-003 FC-1).
- [x] AC-3: Every registry key has 2–3 in-character variants, seedable
      rotation, and a persona-disabled fallback byte-identical to the
      current literal (PLM-003 FC-7, AC-5 groundwork).
- [x] AC-4: `ruff check assistant tests` and the full suite pass; no file
      outside `persona.py`/`test_persona.py` is modified.
