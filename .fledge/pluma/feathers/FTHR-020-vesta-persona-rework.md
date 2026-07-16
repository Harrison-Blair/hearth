---
id: FTHR-020
title: Vesta persona rework
plumage: PLM-005
status: pipping
priority: P1
depends_on: []
authored: 2026-07-16T02:32:13Z
agent: fledge-orchestrate/planning
fledge_version: 0.5.5
---

# FTHR-020: Vesta persona rework

## Description
Rewrite the assistant's persona from "Calcifer" (small, sharp-tongued fire demon) to "Vesta" (grounded in the Roman goddess of the hearth, home, and family), across `persona.system_prompt` in `default-config.yaml`/`config.yaml`, the persona-character prose in `README.md`, and `hearth/loop.py`'s module docstring — plus a minimal smoke test pinning the shipped persona's key properties. Delivers all of PLM-005's functional/acceptance criteria in one unit; nothing else in the plumage depends on or precedes it.

## Affected Modules
- `default-config.yaml` (`persona:` section, ~lines 59-82) — the reference config; `PersonaConfig.system_prompt`/`brain_guard_prompt` schema defined in `hearth/config.py`. See `.fledge/nest/data-model.md` → Configuration schema.
- `config.yaml` — the active/loaded config; mirror the same `persona.system_prompt` change here (per CLAUDE.md, this is the file the daemon actually loads).
- `README.md` — persona-character prose only (lines ~3, 16, 28, 32, 34, 48, 149, 182 per current grep); leave wake-word-specific lines (16, 18, 20, 186) untouched.
- `hearth/loop.py` — module docstring line 6 ("carrying a Calcifer persona system prompt").
- `tests/test_config.py` (FTHR-003's file, per `.fledge/nest/testing.md` coverage map) — add the new smoke test here; it's the existing home for tests that load real `Settings`/config content, so no new test file is needed.
- **Not touched**: `hearth/persona.py` (no-op `restyle` stub, out of scope per PLM-005), `persona.brain_guard_prompt` (already generic, no Calcifer references), existing test fixture placeholder strings (`"You are Calcifer."` in `test_orchestrator_persona.py`, `test_loop_tools.py`, `test_logging.py`, `test_loop.py`, `test_e2e_veneer.py` — these test mechanism, not shipped content).

## Approach
1. Rewrite `persona.system_prompt` in `default-config.yaml`:
   - Open with the bare line `You are Vesta.` — no titles/epithets (no "goddess of the hearth," no "keeper of the flame").
   - Voice/behavior rules, replacing Calcifer's "short, warm, dryly funny fire demon" framing: warm but measured, few words, steady reassurance, protective/nurturing without being saccharine, unshakeable calm, occasional dry warmth (not comedy).
   - An explicit conflict-de-escalation / non-engagement rule: she does not argue, take sides in disputes, or get drawn into hostility — stays steady, redirects toward calm. Use a stable keyword the test can key on (e.g. "de-escalate" or "does not take sides" / "never argues").
   - Preserve, reworded only where it references "Calcifer": first-person only, never third-person, never claims to be an AI/language model, the existing `consult_brain(query)` tool-use instruction (when/how to use it, never mention the tool to the person) — this is a *carryover*, not a rewrite of mechanism.
   - Update the inline YAML comments referencing "Calcifer" (e.g. line 60's "on = Calcifer character..." and line 61-62's descriptive comment) to Vesta.
2. Copy the same `persona.system_prompt` value into `config.yaml` (the active config the daemon loads) — keep both files in sync, matching current repo convention where `config.yaml` mirrors `default-config.yaml`'s persona block.
3. Update `README.md`'s persona-character prose (identified lines) to describe Vesta consistent with the new voice, without touching the interleaved wake-word lines (those stay "Calcifer" — separate plumage).
4. Update `hearth/loop.py`'s docstring line 6 to reference "Vesta" instead of "Calcifer."
5. No changes to `hearth/config.py` schema, `hearth/persona.py`, or `persona.brain_guard_prompt` — none of PLM-005's criteria touch them.

## Tests
Add to `tests/test_config.py` (loads the real shipped `default-config.yaml` via `yaml.safe_load` directly — simplest way to pin shipped content without fighting `Settings`' search-path resolution):
- `test_default_persona_prompt_is_vesta` — loads `default-config.yaml` from the repo root, asserts `persona.system_prompt` contains `"You are Vesta."` and does not contain `"Calcifer"` (case-insensitive). Pins AC-1, AC-5.
- `test_default_persona_prompt_has_no_mythological_titles` — asserts the prompt does not contain title/epithet phrases like `"goddess"` or `"keeper of the"` (case-insensitive). Pins AC-1.
- `test_default_persona_prompt_has_deescalation_rule` — asserts the prompt contains the stable de-escalation marker chosen in step 1 (e.g. `"de-escalat"`, case-insensitive substring match so exact tense/wording can vary). Pins AC-3.
- `test_default_persona_prompt_retains_consult_brain_instruction` — asserts the prompt still contains `"consult_brain"`. Pins AC-4.

Implementation order (fixed): (1) write all four tests above against the **current, unmodified** `default-config.yaml` (still "Calcifer") and confirm they FAIL for the expected reason (asserting "Vesta"/de-escalation text that isn't there yet, or asserting "Calcifer" absence that isn't true yet) — capture this output verbatim in the evidence file; (2) rewrite the config per the Approach; (3) confirm all four tests pass, and run the full `pytest` suite to confirm no existing test (the Calcifer-placeholder fixture tests) broke.

## Acceptance Criteria
- [x] AC-1: The tests listed above were observed failing before implementation and pass after.
- [x] AC-2: `default-config.yaml`'s `persona.system_prompt` opens with `You are Vesta.` and contains no mythological titles/epithets (satisfies PLM-005 AC-1/FC-1).
- [x] AC-3: The system prompt's voice/behavior rules reflect the calm/warm/measured/steady register, with all "fire demon"/"dryly funny" Calcifer characterization removed (satisfies PLM-005 AC-2/FC-2).
- [x] AC-4: The system prompt contains an explicit conflict-de-escalation / non-engagement instruction (satisfies PLM-005 AC-3/FC-3).
- [x] AC-5: The `consult_brain(query)` tool-use instruction is present and functionally unchanged in mechanism (satisfies PLM-005 AC-4/FC-4).
- [x] AC-6: No occurrence of "Calcifer" remains in `default-config.yaml`'s `persona` section (including comments), `config.yaml`'s `persona` section, `README.md`'s persona-character prose (excluding wake-word-specific lines), or `hearth/loop.py`'s module docstring (satisfies PLM-005 AC-5/FC-5/FC-6).
- [x] AC-7: Full existing `pytest` suite passes unmodified — no existing test file's Calcifer-placeholder fixture strings were touched (satisfies PLM-005 AC-7).
