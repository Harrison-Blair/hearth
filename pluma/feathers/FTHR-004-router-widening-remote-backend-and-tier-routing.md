---
id: FTHR-004
title: Router widening remote backend and tier routing
plumage: PLM-001
status: hatching
priority: P0
depends_on: [FTHR-002]
oversight: merge
authored: 2026-07-11T00:15:30Z
agent: fledge-orchestrate/planning
fledge_version: 0.3.0
---

# FTHR-004: Router widening remote backend and tier routing

## Description
Widen the Brain seam from FTHR-002's local-only stub into the full provider router: add the Remote (OpenRouter) backend, populate capability flags on both backends, and implement deterministic, config-driven tier routing with gating and a per-turn override. Fills in `Router.select` and the `routing_decision` reason without changing the frozen signatures from FTHR-002.

## Affected Modules
- `hearth/brain/local.py` — refactor the shared OpenAI-compatible logic into a base class (created in FTHR-002).
- `hearth/brain/remote.py` — `RemoteBackend` (OpenRouter).
- `hearth/brain/router.py` — real `select` logic (replaces FTHR-002's stub body).
- `tests/test_router.py`, `tests/test_remote_backend.py`.
- (See `.fledge/nest/data-model.md` for the `llm` schema and `.fledge/nest/dependencies.md` → OpenRouter.)

## Approach
- **Shared backend base**: extract the httpx OpenAI-compatible request/parse logic into `_OpenAICompatBackend` (in `local.py` or a new `hearth/brain/openai_compat.py`); `LocalBackend` and `RemoteBackend` become thin config-bound subclasses. This is a refactor of FTHR-002 code — behavior-preserving for local; FTHR-002's `test_local_backend_parses_completion` must still pass.
- **`RemoteBackend`**: targets OpenRouter — `base_url` from config (blank → OpenRouter default), model from config, `Authorization: Bearer <key>` where the key is read from the env var named by `backends.remote.api_key_env` (`HEARTH_LLM__OPENROUTER_API_KEY`). `capabilities` from config. Injectable `httpx.AsyncClient` for `MockTransport` tests.
- **`Router.select(tools_available, tier_override) -> Selection`** (signature unchanged):
  - Resolve `tiers.default` → local backend, `tiers.tool` → remote backend; a backend with `enabled=false` is treated as unavailable.
  - If `tier_override` is set → use that tier's backend (reason `"override:<tier>"`).
  - Else if `tools_available`: if the tool tier is enabled and `supports_tools` → tool tier (reason `"tool-turn→tool tier"`); else if a local tool-capable backend is available → local (reason `"tool tier disabled; local fallback"`).
  - Else (no tools) → default tier (reason `"chat-turn→default tier"`).
  - Return `Selection(brain, tier, backend_name, reason)`; the loop logs this as the `routing_decision` event.
- **Gating**: when `backends.remote.enabled=false`, every turn (chat and tool) resolves to local — local-only remains fully functional.

## Tests
Written test-first (write → observe FAIL → implement to green). Hermetic via `httpx.MockTransport`; `pytest`/`asyncio_mode=auto`:
- `test_remote_backend_auth_and_parse` — `RemoteBackend` sends the `Bearer` key and parses an OpenAI-compatible response into a `BrainResult`. (AC-2)
- `test_tool_turn_routes_to_tool_tier` — `select(tools_available=True)` with remote enabled returns the remote backend, `tier="tool"`. (AC-3)
- `test_chat_turn_routes_to_default` — `select(tools_available=False)` returns local, `tier="default"`. (AC-3)
- `test_remote_disabled_falls_back_to_local` — remote `enabled=false` → a tool turn returns local (reason records the fallback). (AC-4)
- `test_tier_override_forces_tier` — `tier_override="tool"` returns the tool tier regardless of `tools_available`. (AC-3)
- `test_local_backend_still_parses` — FTHR-002's local parse behavior is preserved after the base-class refactor. (AC-2)

## Acceptance Criteria
- [x] AC-1: The tests listed above were observed failing before implementation and pass after.
- [x] AC-2: A Remote (OpenRouter) backend implements the `Brain` protocol alongside Local, both advertising `supports_tools`/`supports_streaming`/`context_window`/`cost_tier` (satisfies PLM-001 FC-3).
- [x] AC-3: Tier selection is deterministic and config-driven via declared tier roles, with tool-turn → tool tier, chat-turn → default tier, and a working per-turn override; no complexity heuristic (satisfies PLM-001 FC-4, FC-5).
- [x] AC-4: With the remote tier disabled by config, all turns (chat and tool) are served by local and the spine is fully functional local-only (satisfies PLM-001 FC-6, contributes to PLM AC-4).
- [x] AC-5: The `routing_decision` event records the selected tier, backend, and reason for each turn (contributes to PLM-001 FC-12).
