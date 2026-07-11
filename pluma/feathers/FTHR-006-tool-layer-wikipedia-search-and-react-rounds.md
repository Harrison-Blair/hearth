---
id: FTHR-006
title: Tool layer wikipedia search and ReAct rounds
plumage: PLM-001
status: egg
priority: P0
depends_on: [FTHR-003, FTHR-004]
oversight: merge
authored: 2026-07-11T00:18:51Z
agent: fledge-orchestrate/planning
fledge_version: 0.3.0
---

# FTHR-006: Tool layer wikipedia search and ReAct rounds

## Description
Give the ReAct loop a real tool. Populates the FTHR-002 registry seam with exactly one tool — an async Wikipedia search — and extends the loop with Thought → Action → Observation rounds: dispatching tool calls, feeding observations back, emitting the content-free `ToolActivity` signal, and logging `tool_call`/`observation` events. This is the turn that proves tool-calling works end-to-end and exercises tool-tier routing (FTHR-004) and the veneer's `ToolActivity` forwarding (FTHR-003).

## Affected Modules
- `hearth/tools/wikipedia.py` — `wikipedia_search` + its `ToolSpec`.
- `hearth/tools/registry.py` — register the one tool (populates the empty FTHR-002 seam).
- `hearth/loop.py` — add tool rounds, `ToolActivity` emission, `tool_call`/`observation` logging (edits FTHR-002's loop; not touched by FTHR-003/004).
- `tests/test_wikipedia.py`, `tests/test_loop_tools.py`.
- (Config `tool` section from FTHR-001; `.fledge/nest/dependencies.md` → Wikipedia REST; httpx already a dep.)

## Approach
- **`wikipedia.py`**: `async def wikipedia_search(query: str, *, client: httpx.AsyncClient) -> str` calling the Wikipedia REST search endpoint (`/w/rest.php/v1/search/page?q=<query>&limit=<result_count>`), returning a summary of the top results truncated to `max_chars`. Config from `config.tool.wikipedia` (`endpoint`, `result_count`, `max_chars`, `lang`, `timeout`). Injectable client for `MockTransport` tests. Module-level `SPEC = ToolSpec(name="wikipedia_search", description="Search Wikipedia and return short summaries.", parameters={"type":"object","properties":{"query":{"type":"string"}},"required":["query"]}, label="search")`.
- **`registry.py`**: register `wikipedia_search` → `specs()` returns `[SPEC]`; `async dispatch(name, args)` validates the name and calls `wikipedia_search(**args)`. Shape unchanged so future tools register the same way.
- **`loop.py` tool rounds** (extends `run_turn`): `tools_available = bool(registry.specs()) and config.agent.tool_mode != "off"`. When available: `sel = router.select(tools_available=True)`; `result = await sel.brain.complete(messages, tools=registry.specs())`. While `result.tool_calls` and `round < config.agent.max_tool_rounds`: for each call — `await emit(ToolActivity(turn_id, "start", spec.label))`; append `tool_call` event (name + arguments + provenance); `obs = await registry.dispatch(name, args)`; append `observation` event (result + provenance); `await emit(ToolActivity(turn_id, "end", spec.label))`; append an assistant tool-call message + a tool-result message to `messages`; re-`complete`. On a text result → `persona.restyle` → append `final_answer` → return. Enforce `config.agent.turn_timeout_s`; stop at `max_tool_rounds` and answer with what's available. Pure-chat path (no tools/`tool_mode="off"`) is unchanged from FTHR-002.

## Tests
Written test-first (write → observe FAIL → implement to green). Hermetic via `httpx.MockTransport`; fake backend scripted to return a tool call then a final answer; `pytest`/`asyncio_mode=auto`:
- `test_wikipedia_search_parses` — canned Wikipedia REST body → a truncated summary string; respects `result_count`/`max_chars`. (AC-2)
- `test_loop_tool_round_incorporates_observation` — backend returns a `tool_call`, loop dispatches (stubbed observation), re-queries, final answer reflects the observation; `tool_call` + `observation` events are logged for the turn; `ToolActivity` start/end were emitted through the sink. (AC-3, AC-4)
- `test_tool_turn_uses_tool_tier` — a tool-available turn calls `router.select(tools_available=True)` and passes `tools` to `complete`. (AC-3)
- `test_max_tool_rounds_cap` — a backend that always returns tool_calls stops after `max_tool_rounds` and still returns a final answer. (AC-5)
- `test_toolactivity_label_only` — emitted `ToolActivity` carries only `phase` + `label` (`"search"`), never the query/args/observation. (AC-4)

## Acceptance Criteria
- [ ] AC-1: The tests listed above were observed failing before implementation and pass after.
- [ ] AC-2: The registry holds exactly one tool behind an interface that admits future tools unchanged, and `wikipedia_search` returns a summary hermetically (satisfies PLM-001 FC-8).
- [ ] AC-3: The ReAct loop performs a real tool call routed to the tool tier and incorporates the returned observation into its final answer (satisfies PLM-001 FC-7, contributes to PLM AC-3).
- [ ] AC-4: `tool_call` and `observation` events are logged per turn, and the `ToolActivity` signal emitted to the veneer carries only a coarse label (satisfies PLM-001 FC-12, FC-10, contributes to PLM AC-6).
- [ ] AC-5: Tool rounds are capped at `config.agent.max_tool_rounds` (satisfies PLM-001 FC-7).
