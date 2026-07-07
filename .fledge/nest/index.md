---
generated: 2026-07-07T07:06:00Z
commit: 02f839d7a116780b02510c2d5b339c23c64a51f5
agent: fledge-forager
fledge_version: unknown
---

# Context Index

Regenerated context for `personal-assistant` — an offline-first voice assistant (daemon `assistant/` + monitor TUI `tui/`). This regeneration gives the **web-search capability** special attention (providers in `assistant/search/`, the agentic `WebSearchSkill`, `WebSearchConfig`, `_build_search` wiring, and the search test seams) because upcoming work adds AI-first search adapters. Load docs by the `Read this when:` lines below.

## architecture.md
Explains the single async pipeline loop, interface-per-capability, `app.py` as sole composition root, the LLM tool-calling router + verification loop, remote-as-accelerator fallback chains, shared `StandDown`/`AudioArbiter` state, and the one-directional TUI supervisor. Includes a dedicated section on the web-search capability's architecture and how a new provider slots in.
Read this when: you need the mental model of how components fit, why the graph stays acyclic, or where the search path sits in the whole system before changing it.

## modules.md
Directory-by-directory map (root, `assistant/` broken into app/core/audio/io/search/skills/services/stubs, `tui/`, `training/`+`models/`, `packaging/`, `pluma/`+`docs/`, `tests/`, `.github/`) with key files and a "Look here for:" pointer each. Calls out `assistant/search/` and `assistant/skills/web_search.py` as the search focus.
Read this when: you know what you need to change but not which files/directory hold it.

## conventions.md
The rules a change must follow: async-everywhere, ABC-in-`base.py`, `app.py`-only wiring, primitives-not-`Config`, config-as-single-source-of-truth, graceful degradation, remote-behind-interface, skill plug-in routing, prompt-injection defense for web content, persona-scoped-to-speech, logging/`@@STATE`, and the 40×30 touch-first TUI rules.
Read this when: you are writing code and want it to match existing style/patterns — especially the injection-defense and provider conventions a new search backend must honor.

## data-model.md
Every core type and schema: `core/events.py` records, `Verdict`, `ChatResponse`, the **`SearchResult`/`SearchProvider` seam**, NLU/calendar/weather dataclasses, the SQLite `reminders`/`announced_events`/`blocked_titles` schemas, and all `*Config` models — with `WebSearchConfig` fields fully enumerated.
Read this when: you need exact field names/types/defaults — particularly to shape a new `SearchResult` mapping or add a keyed-provider config field.

## dependencies.md
Third-party libs, external services, and system tools with usage notes, organized by concern and mapped to the per-capability optional extras. Includes a "web-search dependency picture" (today ddgs+httpx, keyless; AI-first adds httpx calls + an API key per provider, SearXNG noted as a roadmap keyless option).
Read this when: you are adding/removing a dependency, choosing how a new provider makes HTTP calls, or reasoning about extras/packaging impact.

## entry-points.md
How to run/build/test the project (daemon, TUI, install, PyInstaller release, CI) and the public interfaces execution flows through: `VoicePipeline`, `Orchestrator`, `SkillRegistry`/`Skill`, `LLMProvider`, control channel, and the **web-search interfaces (`SearchProvider` ABC, `WebSearchSkill`, and `_build_search` — the function a new provider must be added to)**.
Read this when: you need to run something, or you need the signature/entry seam for the pipeline, a skill, or the search capability.

## testing.md
Suite structure, `asyncio_mode=auto`, and the `httpx.MockTransport`/`FakeX` stubbing patterns; the core/capabilities/TUI/eval groupings; the 40-column overflow gate; and the offline eval harness. Devotes a section to the **four search test files and the exact seam-contract a new provider's tests must satisfy**.
Read this when: you are writing or running tests — above all when adding a search provider and need to mirror `test_wikipedia_provider.py`/`test_multi_search.py`/`test_web_search_skill.py`.

## domain.md
Glossary of the project's vocabulary — voice pipeline, routing/reasoning, calendar/scheduling, wake-word training, deployment/specs — with a dedicated **web-search cluster** (AI-first search, fan-out, round-robin merge, assess loop, injection neutralization, SearXNG).
Read this when: a term in the code or a spec is unfamiliar, or you want precise language for a plan.
