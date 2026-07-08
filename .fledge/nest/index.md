---
generated: 2026-07-07T22:56:23Z
commit: 58fb2ba9bbeefc5db7d530261bcb3450573048fa
agent: fledge-forager
fledge_version: unknown
---

# Context Index

Regenerated context for the offline-first voice assistant ("Calcifer") + monitor TUI at commit `58fb2ba`. Reflects the three most recent plumages: PLM-001 (self-update/restart-in-place), PLM-002 (AI-first web search: Tavily/Exa + query routing), PLM-003 (persona-flavored revoice seam + canned templates). The upcoming feature targets the **LLM provider path** (`assistant/llm/`, `app.py:_build_llm`, `LlmConfig`); that path is given first-class coverage in architecture, modules, conventions, and data-model.

## architecture.md
The runtime as a whole: the async pipeline loop (wake→record→STT→route→skill→speak), the orchestrator tool-calling loop, the single composition root, the interface-per-capability seams, shared runtime state, and how PLM-001/002/003 thread through it — plus a dedicated LLM-path section (the three providers + `_build_llm` dispatch).
Read this when: you need the big picture, how subsystems connect, why a seam exists, or where the LLM/routing/persona flow lives before making a cross-cutting change.

## modules.md
Directory-by-directory map of both packages (`assistant/`, `tui/`) plus training, packaging, planning specs, and docs — each with purpose, key files, and a "look here for" pointer. The `assistant/llm/` entry is flagged high-priority.
Read this when: you need to locate the file/module that owns a concern, or orient before diving into one subsystem.

## conventions.md
The rules to follow: async-everywhere, DI-by-primitives with `app.py` as the only wiring point, config-as-source-of-truth with `ASSISTANT_*` overrides, fail-open degradation, the LLM provider conventions (pooled httpx, retry classification, fallback semantics), the persona/revoice invariants (persona-free routing, digit guard, `voiced` bypass), storage/scheduling patterns, and TUI/style/tooling rules.
Read this when: writing or reviewing code — especially adding an LLM provider, a skill, a config field, or anything touching persona/revoice.

## data-model.md
Every core type: `core/events.py` pipeline records (`SkillResult` with `restart`/`voiced`), the LLM contract (`LLMProvider`, `ChatResponse`, `LLMResponseError.retryable`, provider constructor signatures), verify/verdict, capability payloads (search/weather/calendar/timespec), the full `Config`/`LlmConfig` field lists, and the two SQLite schemas.
Read this when: you need a field name, a constructor signature, the exact `LlmConfig` surface, or a DB table shape.

## dependencies.md
Third-party libs deduplicated by the per-capability extras table (tts/wake/stt/vad/llm/nlu/scheduling/search/gcal/aec/tui), external services (Ollama, OpenCode Zen, Tavily/Exa, Google Calendar, Open-Meteo) as optional accelerators behind local fallbacks, native/system deps, PyInstaller packaging, and the isolated ROCm training stack. Python pinned to 3.12.
Read this when: adding a dependency, choosing an extra, wiring a new external service, or debugging a native/build/version issue.

## entry-points.md
How to run/test/build/provision (commands), the daemon composition path (`main`/`_run`/`_build_llm` — where a new LLM provider is registered), the capability ABCs to implement, the skill interface, scheduling/storage/self-update entry points, TUI supervision, and training CLIs.
Read this when: running or building the project, or you need the exact function/interface where execution enters a subsystem you're changing.

## testing.md
pytest + `asyncio_mode=auto`, offline-by-stub. The httpx.MockTransport wire pattern and the specific LLM provider test seams (`test_zen_provider(_guards)`, `test_ollama_provider`, `test_fallback_provider`, `tests/eval/`), the spy-TTS persona-flavor invariant, the 40×30 TUI overflow gate, and coverage by area — plus the test-first discipline every feather follows.
Read this when: writing tests for a change (start from the nearest existing pattern), especially LLM-provider or persona work, or verifying what's already covered.

## domain.md
Glossary: the Calcifer persona/revoice model, voice-pipeline terms (wake/VAD/preroll/barge-in/AEC/stand-down), LLM/routing vocabulary (tool call, verify loop, tier, retryable, Zen, think), search/calendar/time terms, self-update terms, wake-training terms, the fledge planning vocabulary (plumage/feather/fledged), and reference-architecture concepts from `docs/`.
Read this when: you hit an unfamiliar term in code, specs, or these docs, or need the precise meaning of a persona/LLM/pipeline concept.
