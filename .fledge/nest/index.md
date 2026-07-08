---
generated: 2026-07-08T00:34:07Z
commit: 0a67e65dc3d33b2e9c911f1296eef515124fa678
agent: fledge-forager
fledge_version: unknown
---

# Context Index

Regenerated context for the personal-assistant repo (offline-first voice assistant "Calcifer" + monitor TUI). This nest reflects post-PLM-004 reality: the LLM layer is a vendor-neutral OpenAI-compatible gateway (`GATEWAYS` table with `openrouter` + `opencode-zen`) plus local Ollama and an exception-based fallback; `config.yaml` runs OpenRouter as primary; secrets are separated from config. `OpenCodeZenProvider`/`opencode_zen_provider.py` no longer exist. Load docs below by the `Read this when:` routing lines.

## architecture.md
The system as a whole: the async wake→record→STT→route→skill→TTS pipeline, interface-per-capability, `app.py` as composition root, the LLM provider path (gateway table + fallback + boot health check), skill/orchestrator routing, persona/revoice flavoring, proactive schedulers, the one-directional TUI, and config/secrets separation.
Read this when: onboarding, tracing how a request flows end-to-end, or deciding which layer a change belongs in.

## modules.md
Per-module map (purpose → key files → "look here for") covering both packages (`assistant/`, `tui/`) and every top-level directory (training, packaging, pluma specs, tests, root). Notes exactly which files hold the LLM path, config/secrets, and each capability.
Read this when: you need to locate the file/symbol for a subsystem before editing, or want the concrete file list for an area.

## conventions.md
The rules to follow: layering/ABC discipline, async, config-as-truth + `ASSISTANT_*` precedence, the secrets-in-env / per-provider-key pattern, offline-first degradation, LLM gateway/retry/fallback conventions, persona-only-on-speech invariant, SQLite/logging idioms, per-capability extras, and the 40-column TUI grid.
Read this when: writing or reviewing code and you need the idiom (especially for config, secrets, LLM providers, or adding a tunable).

## data-model.md
Concrete types and schemas: pipeline records (`events.py`), LLM types (`ChatResponse`, `GATEWAYS`, wire shapes), the verify `Verdict`, all 16 `*Config` models with `LlmConfig` and `WebSearchConfig` spelled out, NLU/calendar extraction types, capability value types, the SQLite tables, and the shipped config profiles (config.yaml OpenRouter vs default-config vs .env.example).
Read this when: adding a config field or secret, changing a provider's data, touching the DB schema, or needing exact field names/defaults.

## entry-points.md
How to run/build (daemon, TUI, install, release, smoke tests) and every public seam: the config entry + precedence, the full `app.py` LLM-building functions (`_build_llm`/`_build_one_llm`/`_gateway_base_url`/`_llm_unhealthy_warning`), the `LLMProvider`/`Skill`/`SkillRegistry`/capability-provider interfaces, and the TUI control channel.
Read this when: wiring a new provider/skill, changing LLM construction or health/diagnostics, or figuring out how to launch/verify something.

## dependencies.md
Every external library and service with what uses it, organized by core vs per-capability extras (`[llm]`, `[tts]`, `[search]`, `[gcal]`, `[tui]`, …), the external LLM/search/weather/calendar services, packaging/CI tooling, isolated training deps, and how tests stub all of it.
Read this when: adding a dependency, choosing the right extra, or understanding what a service/lib is for and whether it's optional.

## testing.md
The pytest setup (`asyncio_mode=auto`, hermetic, `.[dev]` only) and how isolation is done (MockTransport, native stubs, `:memory:` SQLite, scripted LLMs), plus a coverage map naming the exact config/LLM/orchestrator/skill/TUI test files and the opt-in live+replay eval harness.
Read this when: writing tests for a change, finding the test that guards a behavior (especially LLM/config), or running the eval gates.

## domain.md
Glossary of the project's vocabulary — pipeline/routing, persona/speech, the LLM provider layer (gateway, OpenRouter, fallback, transient), config/secrets terms (per-provider secret, override), capabilities, runtime plumbing, wake training, and fledge spec terms.
Read this when: a term in code/specs/tickets is unfamiliar, or you want shared language before writing a plumage/feather.
