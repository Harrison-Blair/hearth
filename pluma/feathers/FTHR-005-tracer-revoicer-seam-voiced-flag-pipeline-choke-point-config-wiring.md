---
id: FTHR-005
title: "Tracer: Revoicer seam — voiced flag, pipeline choke point, config, wiring"
plumage: PLM-003
status: pipping
priority: P1
depends_on: []
authored: 2026-07-07T17:57:07Z
agent: fledge-orchestrate/planning
fledge_version: 0.2.0
---

# FTHR-005: Tracer: Revoicer seam — voiced flag, pipeline choke point, config, wiring

## Description
The tracer bullet for PLM-003: a thin, working end-to-end slice proving the
revoice architecture. After this feather, with persona enabled, a
deterministic skill reply (e.g. clock) reaching `pipeline._speak` is restyled
in Calcifer's voice by a live LLM call — with every safety net active
(failure-cooldown circuit, bounded timeout, digit-preservation guard, plain
fallback) — while already-persona'd LLM output passes through untouched via
the new `voiced` flag. Scheduler/watcher injection (FTHR-008) and template
adoption (FTHR-007) widen this slice.

Includes the `voiced=True` marks on GeneralSkill, WeatherSkill,
WebSearchSkill, and the verify `rewritten_speech`/restyle paths — they must
land with the seam, or those replies would be double-flavored between waves.

Satisfies PLM-003 FC-2, FC-3, FC-4 (pipeline site), FC-5, FC-6, FC-8.

## Affected Modules
- **`assistant/core/revoice.py` (new)** — `Revoicer`: holds the `LLMProvider`,
  persona segment, timeout, and circuit state; `async revoice(text) -> str`.
- **`assistant/core/events.py`** — `SkillResult.voiced: bool = False`.
- **`assistant/core/pipeline.py`** — `_speak(text, *, voiced=False)` seam:
  not-voiced text passes through the injected `Revoicer` before sentence
  splitting; call sites propagate `result.voiced` (and `voiced=True` for the
  already-persona'd verify `on_say` feedback).
- **`assistant/core/config.py`** — `PersonaConfig.revoice_enabled: bool = True`,
  `revoice_timeout_s: float = 5.0`.
- **`config.yaml` / `default-config.yaml`** — mirror the two new fields.
- **`assistant/app.py`** — construct `Revoicer` (persona enabled+strength,
  LLM provider, config) and inject into `VoicePipeline`; seed the circuit
  from the existing boot health check.
- **`assistant/skills/general.py`, `weather.py`, `web_search.py`,
  `assistant/core/orchestrator.py`** — mark persona-bearing results
  `voiced=True` (one-line each; LLM-offline failure strings stay unvoiced
  until FTHR-007's templates).

## Approach
Test-first. `Revoicer.revoice(text)`:
1. Passthrough (return `text`) when persona or `revoice_enabled` is off, or
   the circuit is open (recent failure / seeded-unhealthy) — no LLM call, no
   added latency.
2. Otherwise one `chat` call — system prompt = persona segment + a fixed
   restyle instruction ("restyle this exact reply in your voice; do not
   answer, add, or remove information; keep every time, date, and number
   byte-exact"), user content = the plain string. No conversation history.
   Bounded by `asyncio.wait_for(..., revoice_timeout_s)`.
3. Guard: every `\d+` sequence in the plain string must appear verbatim in
   the output; any miss, empty output, timeout, or exception → return the
   plain string, log one warning, open the circuit (cooldown before retry).

The pipeline stays coupled to `Revoicer` as an injected optional (`None` in
existing tests → passthrough), constructed only in `app.py` per the
composition-root rule. The seam sits at the top of `_speak` so barge-in,
sentence splitting, and state emission behave identically on flavored and
plain text.

## Tests
New `tests/test_revoice.py` (stub `LLMProvider`, no network):
- restyles via the stub and returns the styled text (digits preserved)
- timeout (hanging stub) → plain string + warning, within `revoice_timeout_s`
- stub error / empty reply → plain string
- digit guard: stub drops/mutates a number → plain string
- open circuit (after a failure / seeded unhealthy) → plain immediately,
  zero LLM calls
- `revoice_enabled=False` or persona disabled → passthrough, zero LLM calls
- the revoice prompt contains the persona segment and the plain text but not
  conversation history

Extended `tests/test_pipeline.py` (spy TTS):
- unvoiced `SkillResult` speech is revoiced before TTS; voiced results and
  persona-disabled runs reach TTS byte-identical

Extended `tests/test_general_skill.py` / `test_weather.py` /
`test_web_search_skill.py` / `test_orchestrator_verify.py`:
- persona-bearing results carry `voiced=True`

Implementation order is fixed: (1) write the tests; (2) confirm they FAIL
against unchanged code for the expected reason; (3) implement until they pass.

## Acceptance Criteria
- [ ] AC-1: The tests listed above were observed failing before
      implementation and pass after.
- [ ] AC-2: End-to-end with persona enabled, an unvoiced skill reply is
      revoiced before TTS with all digit sequences intact; with persona
      disabled the spoken text is byte-identical to today (PLM-003 AC-1).
- [ ] AC-3: Timeout, error, empty output, and open-circuit cases all speak
      the plain string — bounded by `revoice_timeout_s`, immediate when the
      circuit is open, warning logged, no reply ever dropped (PLM-003 AC-3).
- [ ] AC-4: A revoiced output missing/mutating any digit sequence is
      discarded for the plain string (PLM-003 AC-4).
- [ ] AC-5: `revoice_enabled` and `revoice_timeout_s` are typed
      `PersonaConfig` fields mirrored in both yamls; `revoice_enabled: false`
      makes zero revoice LLM calls while LLM-skill replies stay flavored
      (PLM-003 AC-6).
- [ ] AC-6: `ruff check assistant tests` and the full suite pass without
      native extras or network (PLM-003 AC-8).
