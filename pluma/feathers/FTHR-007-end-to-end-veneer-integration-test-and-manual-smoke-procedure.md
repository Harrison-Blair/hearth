---
id: FTHR-007
title: End-to-end veneer integration test and manual smoke procedure
plumage: PLM-001
status: hatching
priority: P0
depends_on: [FTHR-006]
oversight: merge
authored: 2026-07-11T01:37:25Z
agent: fledge-orchestrate/planning
fledge_version: 0.3.4
---

# FTHR-007: End-to-end veneer integration test and manual smoke procedure

## Description
Closes PLM-001's plumage-level verification gap: every prior feather (FTHR-001–006) is individually well-tested at the component/unit level, but no single test assembles the real `Veneer` + `Loop` + `Router` + `ToolRegistry` + `EventLog` together, driven over an actual WebSocket connection, for a multi-turn conversation that includes a Wikipedia tool-use turn. This feather adds that assembled integration test (hermetic — stubbed LLM and Wikipedia HTTP, real WebSocket) and writes down a manual smoke procedure a human can run against live Ollama, live OpenRouter, and the live Wikipedia API, since this Phase 0 environment has no access to those services to execute it automatically.

## Affected Modules
- `tests/test_e2e_veneer.py` — new assembled integration test(s), reusing `hearth/veneer/client.py`'s `send_turn` as the test's client side (see `.fledge/nest/testing.md`).
- `MANUAL_SMOKE.md` (new, repo root) — the documented manual procedure (no existing `docs/` convention in this repo; a root-level doc mirrors `CLAUDE.md`'s placement).

## Approach
- **Integration test** (`tests/test_e2e_veneer.py`): construct the real `EventLog` (temp sqlite path), `Router` (from a `config.llm` fixture with both `local` and `remote` backends, injected `httpx.AsyncClient` using `MockTransport`), `ToolRegistry` (wired with a `client` whose `MockTransport` serves a canned Wikipedia REST response), `Loop`, and `Veneer`. Start `Veneer.serve` on an ephemeral port (`port=0` or a fixed high test port) inside the test via `asyncio.create_task`, connect a real `websockets.connect` client, and drive:
  1. A plain chat turn (no tool) — assert `answer`/`done` and the event log's `user_input`/`routing_decision`/`final_answer` rows.
  2. A second turn on the same connection/session whose scripted LLM response returns a `wikipedia_search` tool call, then a final answer — assert the wire sees `tool_activity{phase:start,label:"search"}` and `tool_activity{phase:end,label:"search"}` (and nothing else keyed beyond the AC-6 whitelist) before `answer`/`done`, and that the event log has `tool_call`+`observation` rows for that turn alongside the earlier turn's rows (multi-turn history intact, per FC-14).
  3. Repeat step 2's tool-turn shape with `tier_override`/`remote.enabled=true` config so the scripted backend is the remote (OpenRouter-shaped) `MockTransport` instead of local — assert the same event-sequence shape and wire behavior (satisfies PLM-001 AC-2's "same event sequence shape, same veneer contract behavior").
  4. With `remote.enabled=false`, repeat the tool-turn and assert `routing_decision`'s `backend_name` is `local` (satisfies PLM-001 AC-4 assembled, not just at the router-unit level).
- This test file does not modify any non-test module — it is purely additive, assembling already-built, already-tested components.
- **`MANUAL_SMOKE.md`**: numbered steps — (1) local-only: start Ollama with the configured model, set `.env`/`config.yaml` for local-only (`llm.backends.remote.enabled: false`), run `hearth run`, in a second terminal run `python -m hearth.veneer.client`, type a plain question and a question that should trigger the Wikipedia tool (e.g. "who was Ada Lovelace"), confirm a sensible spoken-style answer and no crash. (2) remote-tier: set `HEARTH_LLM__OPENROUTER_API_KEY` in `.env`, enable the remote backend, repeat the tool-triggering question, confirm the `routing_decision` event (inspect `hearth.db` via `sqlite3` or a one-liner) shows `tier=tool, backend_name=remote`. (3) note expected failure modes (no Ollama running, no key set) and how to tell them apart from a real bug. This is documentation only — no code changes — and is not itself a gating automated check (satisfies PLM-001 FC-15's "documented as a manual smoke check, not a gating automated test").

## Tests
Written test-first (write → observe FAIL for the expected reason → implement to green). `tests/test_e2e_veneer.py`, hermetic (real WebSocket loopback, `httpx.MockTransport` for both LLM and Wikipedia — no real network), `pytest`/`asyncio_mode=auto`:
- `test_e2e_multiturn_chat_and_tool_use` — plain turn then tool-use turn on one connection/session; asserts wire messages, event log rows, and history continuity across both turns. (AC-2, covers PLM-001 AC-1/AC-6 assembled)
- `test_e2e_remote_tier_tool_turn_same_shape` — tool-use turn routed to the remote tier; asserts the same event-sequence shape as the local-tier case. (AC-3, covers PLM-001 AC-2 assembled)
- `test_e2e_remote_disabled_stays_local` — `remote.enabled=false`; a tool-use turn still resolves to `local` end-to-end. (AC-4, covers PLM-001 AC-4 assembled)

## Acceptance Criteria
- [ ] AC-1: The tests listed above were observed failing before implementation and pass after.
- [ ] AC-2: An assembled integration test drives a real `Veneer` over an actual WebSocket connection through a multi-turn conversation — a plain chat turn and a Wikipedia tool-use turn on the same session — asserting the full event set (`user_input`, `routing_decision`, `tool_call`, `observation`, `final_answer`) is logged and the wire contract (`tool_activity`/`answer`/`done`) is followed, with history reconstructed correctly across turns (satisfies PLM-001 AC-1, AC-6 with an assembled proof rather than composed unit tests).
- [ ] AC-3: The same assembled scenario, run with the remote tier selected for the tool-use turn, produces the same event-sequence shape and veneer contract behavior (satisfies PLM-001 AC-2 with an assembled proof).
- [ ] AC-4: The same assembled scenario, run with the remote tier disabled by config, resolves the tool-use turn to the local tier end-to-end (satisfies PLM-001 AC-4 with an assembled proof).
- [ ] AC-5: `MANUAL_SMOKE.md` exists at the repo root and documents a step-by-step procedure for a human to exercise the spine against live Ollama and live OpenRouter, including a Wikipedia-triggering question, with expected results and how to distinguish environment issues (no Ollama, no key) from real bugs (satisfies PLM-001 AC-3's live-API manual-check requirement and FC-15/AC-8's "documented" requirement).
