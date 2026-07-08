---
id: FTHR-011
title: Vendor-agnostic remote-gateway diagnostics in app.py
plumage: PLM-004
status: egg
priority: P2
depends_on: [FTHR-010]
authored: 2026-07-07T23:30:26Z
agent: fledge-orchestrate/planning
fledge_version: 0.2.0
---

# FTHR-011: Vendor-agnostic remote-gateway diagnostics in app.py

## Description
Widens the tracer: makes `app.py`'s boot diagnostics name whichever remote gateway
is selected instead of assuming OpenCode Zen. Today two branches hard-code
`provider == "opencode-zen"` — the endpoint shown in the boot "Config:" log line,
and the LLM-unhealthy warning. This feather drives both off the `GATEWAYS` table
FTHR-010 introduced, so `provider: openrouter` logs the OpenRouter endpoint and,
when unreachable at boot, emits a warning naming OpenRouter (not Zen). Local Ollama
diagnostics are unchanged. No runtime pipeline behavior changes — purely
operator-facing accuracy.

Satisfies PLM-004 FC-5; establishes AC-4.

## Affected Modules
- **`assistant/app.py`** — the `main()` boot-log endpoint selection
  (`base_url if provider == "opencode-zen" else host`, ~L183) and the `_run()`
  LLM-unhealthy warning (Zen-specific vs Ollama, ~L241). Introduce
  `_gateway_base_url(cfg)` and reuse it in both the boot log and `_build_one_llm`
  (removing FTHR-010's inline duplication); replace both `== "opencode-zen"` checks
  with `provider in GATEWAYS`. See `.fledge/nest/architecture.md` → "The LLM path".

## Approach
Test-first. Factor two small seams so the diagnostics are unit-testable without
booting the daemon:
- `_gateway_base_url(cfg) -> str | None`: `cfg.base_url or
  GATEWAYS[cfg.provider]["base_url"]` for a gateway provider, else `None` (Ollama).
  `_build_one_llm` and the boot-log endpoint both call it.
- `_llm_unhealthy_warning(cfg) -> str`: returns the message — a gateway-generic
  "Remote LLM gateway %s not ready (base_url=%s, model=%s); … verify
  ASSISTANT_LLM__API_KEY …" for a gateway provider, the existing Ollama message
  otherwise. `_run` logs its return.
Keep the wording close to today's for `opencode-zen` continuity; the only functional
change is that the gateway name/URL are interpolated from config+table rather than
fixed to Zen. Never log the key.

## Tests
New `tests/test_app_llm_diagnostics.py` (pure helpers; no daemon boot, no network):
- `_gateway_base_url`: `openrouter` → OpenRouter URL; `opencode-zen` → Zen URL;
  explicit `base_url` overrides; `ollama` → `None`.
- `_llm_unhealthy_warning`: `openrouter` message names "openrouter" and includes the
  OpenRouter base_url + `ASSISTANT_LLM__API_KEY`; `opencode-zen` names that gateway;
  `ollama` gives the "Run `ollama serve`" message.
Implementation order fixed: (1) tests; (2) confirm FAIL against unchanged code (the
helpers don't exist / Zen is hard-coded); (3) implement until green.

## Acceptance Criteria
- [x] AC-1: The tests listed above were observed failing before implementation and
      pass after.
- [x] AC-2: With `provider: openrouter`, the boot "Config:" log shows the OpenRouter
      endpoint and a boot-time unhealthy LLM logs a warning naming OpenRouter (not
      Zen) with its base_url — driven by `GATEWAYS`, with no `== "opencode-zen"`
      check remaining in these branches (PLM-004 AC-4, FC-5).
- [x] AC-3: `provider: opencode-zen` and `provider: ollama` diagnostics are
      unchanged in substance (same endpoint and message content as before).
- [x] AC-4: `ruff check assistant tests` and the full suite pass with no network.
