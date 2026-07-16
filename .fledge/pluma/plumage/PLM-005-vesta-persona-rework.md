---
id: PLM-005
title: Vesta persona rework
status: hatched
priority: P1
authored: 2026-07-16T02:29:29Z
agent: fledge-orchestrate/planning
fledge_version: 0.5.5
---

# PLM-005: Vesta persona rework

## Context
The assistant's current character is "Calcifer" — a small, sharp-tongued fire demon — carried by `persona.system_prompt` (`hearth/persona.py`, `PersonaConfig`, config sections in `default-config.yaml`/`config.yaml`) and referenced throughout `README.md` and `hearth/loop.py`'s docstring. The user wants the assistant reworked into "Vesta," grounded in the Roman goddess of the hearth, home, and family (sources: [Wikipedia](https://en.wikipedia.org/wiki/Vesta_(mythology)), [Medium: The Sacred Flame of Vesta](https://medium.com/@riddickdm/the-sacred-flame-of-vesta-goddess-of-the-hearth-d47e30369b80), [Mythopedia](https://mythopedia.com/topics/vesta)), with a robust, in-depth personality attribution rather than a superficial name swap.

Vesta's mythological character is markedly different from Calcifer's: calm dignity, quiet steadiness, warm protective presence, non-dramatic and non-quarrelsome ("never involved herself in the quarreling of other gods"), austere yet nurturing (titled "Mater" despite her eternal virginity), values purity, domesticity, hospitality, and constancy (the eternal flame as permanence/reliability), and — per the sources — she "existed as an abstract goddess" with no dramatic personal mythology, favoring presence-through-function over personality performance.

This plumage covers only the assistant's **text/voice identity** — the persona system prompt and its user-facing documentation. It deliberately excludes the wake word: renaming/retraining the audio wake-word detector ("Vesta" and "Prometheus" as candidate trigger words) is a separate, disjoint undertaking in the `training/` pipeline (its own venv, synthetic dataset, FPPH/recall gate — no shared files or verification method with this plumage) and is covered by a separate plumage.

## User Stories
- As the assistant's user, I want the assistant to speak and behave as Vesta — calm, warm, steady, protective — instead of Calcifer's sharp-tongued fire-demon voice, so that its personality matches the hearth-goddess identity I've chosen for it.
- As the assistant's user, I want Vesta's mythological character (not just her name) to shape how she responds — including staying out of arguments and disputes — so that the persona rework is a genuine in-depth attribution, not a cosmetic rename.
- As a developer reading the code/docs, I want every persona-character reference in `README.md` and `hearth/loop.py` updated to Vesta, so that the documentation doesn't contradict the shipped persona.

## Functional Criteria
1. FC-1: `persona.system_prompt` (in `default-config.yaml`, mirrored in `config.yaml`) opens with a bare identity line — `You are Vesta.` — with no mythological titles or epithets attached (no "goddess of the hearth," no "keeper of the flame"); everything else in the prompt shapes her voice/behavior from the mythology without narrating it.
2. FC-2: The prompt's voice/behavior rules specify: warm but measured, few words, steady reassurance, protective/nurturing without being saccharine, unshakeable calm, occasional dry warmth (not comedy) — replacing Calcifer's "short, warm, dryly funny" fire-demon register.
3. FC-3: The prompt includes an explicit conflict-de-escalation / non-engagement rule: Vesta does not argue, take sides in disputes, or get drawn into hostility — she stays steady and redirects toward calm.
4. FC-4: The prompt's functional carryover from Calcifer's is preserved in substance (still first-person, never third-person, never claims to be an AI/language model, retains the existing `consult_brain(query)` tool-use instruction unchanged in mechanism) — only the character/voice content changes, not the tool-use contract.
5. FC-5: `README.md`'s persona-character prose (currently describing Calcifer's character: "themed around Calcifer," "answers every turn as Calcifer — warm, dry...," "folded back into Calcifer's voice," and similar) is reworded to describe Vesta consistent with FC-1..FC-3. `README.md`'s wake-word-specific mentions ("Wake word (Calcifer)," `models/wake/calcifer.onnx` path) are left unchanged — out of scope for this plumage.
6. FC-6: `hearth/loop.py`'s module docstring ("carrying a Calcifer persona system prompt") is updated to reference Vesta.
7. FC-7: A minimal, durable smoke test asserts the real shipped `persona.system_prompt` (loaded from config) contains "Vesta", does not contain "Calcifer", and contains a stable marker for the conflict-de-escalation rule (e.g. a keyword like "de-escalat", "argue", or "take sides") — without pinning exact prose wording.

## Acceptance Criteria
- [ ] AC-1: `default-config.yaml`'s `persona.system_prompt` opens with `You are Vesta.` and contains no mythological titles/epithets (FC-1).
- [ ] AC-2: The system prompt's voice/behavior rules reflect the calm/warm/measured/steady register from FC-2, replacing all "fire demon"/"dryly funny" Calcifer characterization.
- [ ] AC-3: The system prompt contains an explicit conflict-de-escalation / non-engagement instruction (FC-3).
- [ ] AC-4: The `consult_brain(query)` tool-use instruction is present and functionally unchanged in mechanism (still tells the orchestrator when/how to use the tool) (FC-4).
- [ ] AC-5: No occurrence of "Calcifer" remains in `default-config.yaml`'s `persona` section, `README.md`'s persona-character prose (excluding wake-word-specific lines), or `hearth/loop.py`'s module docstring (FC-5, FC-6).
- [ ] AC-6: A new automated test (test-first: written, shown failing against the unchanged config, then passing) asserts `persona.system_prompt` contains "Vesta", excludes "Calcifer", and contains the conflict-de-escalation marker (FC-7).
- [ ] AC-7: Full existing test suite (`pytest`) still passes unmodified — no existing test's placeholder fixture strings (e.g. `"You are Calcifer."` in `test_orchestrator_persona.py`, `test_loop_tools.py`, `test_logging.py`, `test_loop.py`, `test_e2e_veneer.py`) are touched, since they test mechanism, not shipped persona content.

## Out of Scope
- Renaming or retraining the audio wake word ("Calcifer" → "Vesta"/"Prometheus") — covered by a separate plumage against the `training/` pipeline.
- Wiring live wake-word detection into the running daemon (`hearth run`) — no `hearth/wake/` module exists today and none is added here.
- `hearth/persona.py`'s `restyle` stage — remains the existing FTHR-011 no-op stub; not touched.
- `persona.brain_guard_prompt` content — audited and found to contain no "Calcifer"/character-specific language already (it already speaks generically of "an internal research subsystem, not the user-facing assistant"), so no change is required for this plumage's scope.
- README/doc lines that describe the wake word specifically (as opposed to the persona character) — left for the wake-word plumage.
- Rewriting existing test fixture placeholder strings (`"You are Calcifer."` etc.) in mechanism-level tests — they test plumbing, not shipped content, and are left as-is per AC-7.

## Open Questions
None outstanding — all decision points raised during interrogation were resolved with the user.
