---
id: FTHR-010
title: Remote brain guard prompt
plumage: PLM-002
status: egg
priority: P1
depends_on: [FTHR-009]
authored: 2026-07-11T02:50:32Z
agent: fledge-orchestrate/planning
fledge_version: 0.3.4
---

# FTHR-010: Remote brain guard prompt

## Description
Small, additive feather layered on FTHR-009's nested consult loop. The remote brain's nested ReAct loop (driven by `hearth/tools/consult.py`'s `BrainConsult`) currently seeds its messages with only the consult query — nothing tells the remote model it's an internal subsystem rather than the user-facing assistant. This feather adds a config-driven guard prompt, prepended as the nested loop's `messages[0]`, instructing the remote brain not to assert an identity or address the user directly. This is defense-in-depth alongside FTHR-009's structural fix (the remote model never reaches the client either way) — it keeps the brain's own tool-reasoning text (which the orchestrator sees as an observation) from drifting into a persona-breaking voice.

## Affected Modules
- `hearth/config.py:79-81` (`PersonaConfig`, extended by FTHR-009 with `system_prompt`) — add `brain_guard_prompt: str`, a neutral research-subsystem instruction, default provided.
- `hearth/tools/consult.py` (`BrainConsult.__call__`, added by FTHR-009) — prepend `Message(role="system", content=config.persona.brain_guard_prompt)` as `messages[0]` before the seeded `Message(role="user", content=query)`, on every nested consult.
- `config.yaml` / `default-config.yaml` — add `persona.brain_guard_prompt` alongside `persona.system_prompt`, with an inline doc comment.
- New `tests/test_brain_guard.py`.

## Approach
- No new types — this is one field on the already-extended `PersonaConfig` plus a one-line prepend in `BrainConsult.__call__`'s message construction.
- The guard text itself: something like "You are an internal research subsystem. Answer factually; do not claim a name or personality, and do not address 'the user' directly — your output is read by another system, not a person." Exact wording is an authoring detail for the implementer, not a spec-fixed string — the AC below tests for the *presence and content intent* of the config value, not an exact string match.
- Keep it config-driven (YAML/env overridable via the existing `HEARTH_PERSONA__BRAIN_GUARD_PROMPT` env path), matching how `system_prompt` is sourced — no hardcoded fallback string embedded only in Python; the default lives in `config.yaml`/`default-config.yaml`.

## Tests
Written test-first in `tests/test_brain_guard.py` (new), reusing FTHR-009's `two_tier_llm_config` fixture and host-keyed `MockTransport` helper:
- `test_nested_request_carries_guard_as_first_message` — drive a `BrainConsult.__call__`, capture the remote-backend request, assert `messages[0] == {"role": "system", "content": <configured brain_guard_prompt>}` and `messages[1]` is the user query.
- `test_guard_prompt_is_config_driven` — construct two configs with different `persona.brain_guard_prompt` values; assert the nested request's `messages[0]["content"]` reflects whichever config was injected (proves it isn't hardcoded).

Implementation order: write `test_brain_guard.py` first against FTHR-009's already-landed `consult.py` (unchanged in this feather until implementation), confirm it fails because `messages[0]` is the user query / `PersonaConfig` has no `brain_guard_prompt` field, then implement the config field + prepend until green.

## Acceptance Criteria
- [ ] AC-1: The tests listed above were observed failing before implementation and pass after.
- [ ] AC-2: Every nested brain request (driven through `BrainConsult`) carries `persona.brain_guard_prompt` as `messages[0]`. Satisfies PLM-002 FC-4.
- [ ] AC-3: The guard text instructs the brain not to assert an identity or address the user — verified by asserting the configured/default string is non-empty and is the literal content of `messages[0]` (content-intent is an authoring choice, not machine-verified semantics).
- [ ] AC-4: `persona.brain_guard_prompt` is config-driven (overridable via YAML or the `HEARTH_PERSONA__BRAIN_GUARD_PROMPT` env var), not hardcoded in `consult.py`.
