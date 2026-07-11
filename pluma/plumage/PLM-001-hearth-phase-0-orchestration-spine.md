---
id: PLM-001
title: "Hearth Phase 0 — Orchestration Spine"
status: hatched
priority: P0
authored: 2026-07-10T23:20:08Z
agent: fledge-orchestrate/planning
fledge_version: 0.3.0
---

# PLM-001: Hearth Phase 0 — Orchestration Spine

## Context

The runtime source tree is absent from this repo — only `config.yaml`/`default-config.yaml`, the trained wake `.onnx`, the `training/` pipeline, and packaging metadata survived the restart (see `architecture.md`: "repo state: mid-restart"). Before any voice-pipeline feature (wake → recorder → STT → LLM → agent → verify → persona → TTS, per the intended cascade in `architecture.md`) can be rebuilt, the project needs a stable spine to attach it to: a way to talk to an LLM through a swappable provider, a loop that can call tools and reason over the result, a boundary that a future UI/voice layer can sit behind without knowing about tool internals, and a durable record of what happened each turn.

Phase 0 builds that spine only — greenfield, single-agent, text-in/text-out over a localhost WebSocket. It deliberately excludes the voice cascade itself, deferring wake/STT/VAD/TTS/AEC/persona-character work to later phases. Every interface Phase 0 defines (the Brain router, the tool registry, the veneer contract, the two memory layers) is the seam later phases attach to; getting these seams right — typed, stubbed where not yet built, and unaffected by what attaches later — is the actual deliverable, not any one feature riding on top of them.

This also re-establishes the project's identity: the runtime package, console command, and entry point are renamed to `hearth` (superseding the old `assistant` naming), with CI, `Makefile`, and distribution artifacts following suit. Configuration continues the two-file model and the FTHR-015 secrets rule already established in this repo (`conventions.md`): secrets live only in `.env`, non-secret tunables live in YAML — Phase 0's new schema inherits this rule rather than relitigating it.

## User Stories

- As the operator (self-hosted, single user), I want a working local-only conversation loop, so that the assistant is usable end-to-end without depending on any remote service or API key.
- As the operator, I want to enable a remote LLM tier by config alone, so that I can trade local privacy for stronger tool-calling capability when I choose to.
- As a developer building later phases (voice cascade, persona character, temporal memory index), I want stable, typed seams (router, tool registry, veneer contract, memory layers) already in place, so that I can attach new capability without modifying or destabilizing the orchestration spine.
- As the operator, I want every turn's decisions and tool activity durably logged, so that behavior is auditable and future features (history, memory indexing) can be built from that record without changing how turns are written.
- As the operator, I want the assistant to be able to look something up (Wikipedia) mid-conversation and use the result in its answer, so that Phase 0 proves the tool-calling loop actually works, not just that it's wired.

## Functional Criteria

1. FC-1: The runtime package is named `hearth`, exposes a console entry point named `hearth`, and CI smoke-test/`Makefile`/release artifact naming reference `hearth` rather than the prior `assistant` naming.
2. FC-2: A new configuration schema is loaded via `pydantic-settings`, reusing applicable real values from the existing `config.yaml`/`default-config.yaml` where they still apply; secret fields never appear in the YAML schema, only as `.env` entries following the `HEARTH_<SECTION>__<PROVIDER>_API_KEY` convention (renamed from the prior `ASSISTANT_` prefix to match the `hearth` rename).
3. FC-3: A single Brain interface exposes two backends — Local (OpenAI-compatible, targets a local Ollama server) and Remote (OpenAI-compatible, targets OpenRouter) — each advertising `supports_tools`, `supports_streaming`, `context_window`, and `cost_tier` capability flags.
4. FC-4: Backends are configured with declared tier roles (`default` = local, `tool` = remote); tier selection is deterministic and config-driven, with no heuristic based on turn complexity.
5. FC-5: A turn dispatched with tools available routes to the `tool` tier if it is enabled and advertises `supports_tools`; otherwise it falls back to a local tool-capable backend. A turn with tools disabled routes to the `default` tier. An explicit per-turn override can force a specific tier.
6. FC-6: When the remote tier is disabled by config, all turns — including tool-using turns — are served by the local tier, and the assistant remains fully functional local-only.
7. FC-7: A single-agent ReAct loop (Thought → Action → Observation) runs multi-turn over the Brain router, calling backends in non-streaming mode and parsing tool calls from complete responses; no agent framework (e.g. LangGraph) is used.
8. FC-8: A tool registry holds exactly one tool — an async Wikipedia search — behind an interface designed so additional tools can register without changing the loop or registry shape; each tool declares a coarse, veneer-safe label (the Wikipedia tool's label is `"search"`).
9. FC-9: Token streaming is not implemented anywhere in the Phase 0 path (backends, loop, or veneer), since draft-then-restyle persona requires a complete answer before restyling; `supports_streaming` is a declared-but-unused capability flag, understood as a known non-breaking future extension for the later voice phase (where TTS latency makes it valuable).
10. FC-10: A localhost WebSocket veneer contract accepts `{turn_id, final_user_transcript}` and emits, all tagged with that `turn_id`: zero or more ToolActivity signals (start/end, carrying only the tool's coarse label — never query, arguments, observations, or results), exactly one final restyled answer, and a terminal Done or Error signal.
11. FC-11: A persona seam runs as the last stage before a final answer leaves the loop, applied only to user-facing final answers (never tool reasoning or structured/intermediate output); in Phase 0 it is a buffered no-op that returns its input unchanged.
12. FC-12: An append-only, event-sourced SQLite log is the canonical source of truth, written synchronously on the write path; each turn appends `user_input`, `routing_decision` (tier/backend chosen and why), `tool_call`, `observation`, `final_answer`, and (on failure) `error` events, each timestamped and carrying provenance; no event is ever updated or deleted.
13. FC-13: A read-side Layer 2 interface exposes the event log as an ordered, cursor-based pull stream; a no-op stub consumer is wired against it, and the synchronous write path is uncoupled from and unaffected by any consumer's presence, absence, or speed — this is the seam a future background indexer (Graphiti/FalkorDB, later phase) attaches to.
14. FC-14: A WebSocket connection constitutes one session with a session id; each turn within it carries a `turn_id`; conversation history is reconstructed by reading recent events from the event log scoped to that session, bounded by a max-history setting — there is no separate history store.
15. FC-15: The automated test suite is hermetic: LLM backends are exercised against an in-process fake OpenAI-compatible endpoint, and the Wikipedia tool against a stubbed HTTP response. A real end-to-end run against live Ollama, live OpenRouter, and live Wikipedia is documented as a manual smoke check and is not a gating automated test.

## Acceptance Criteria
- [ ] AC-1: With only the local tier enabled, a multi-turn conversation — including at least one turn that uses the Wikipedia tool — completes end-to-end over the WebSocket veneer contract, and every turn's defined event set (user_input, routing_decision, tool_call, observation, final_answer) is appended to the event log.
- [ ] AC-2: The same conversation, run with the remote tier enabled and selected by config for tool-using turns, completes successfully with tool-calling working identically from the ReAct loop's perspective (same event sequence shape, same veneer contract behavior).
- [ ] AC-3: The ReAct loop performs a real Wikipedia tool call (against a stubbed HTTP response in the automated suite; against the live API in the manual smoke check) and incorporates the returned observation into its final answer.
- [ ] AC-4: With the remote tier disabled by config, every turn type (pure-chat and tool-using) is served by the local tier and the spine remains fully functional with no dependency on the remote provider.
- [ ] AC-5: The Layer 2 read seam, the veneer contract, and the persona restyle stage each exist as clean, typed interfaces with a stub or no-op implementation behind them, such that a later phase can attach a real implementation without modifying the spine's existing code paths.
- [ ] AC-6: For a tool-using turn, the veneer receives a ToolActivity start/end signal carrying only the tool's coarse label; inspection of every outbound veneer message for that turn confirms no tool query, arguments, or observation content ever crosses the veneer boundary.
- [ ] AC-7: The runtime console command is `hearth`, and CI, `Makefile`, and release artifact naming reference `hearth` rather than `assistant`.
- [ ] AC-8: The automated test suite runs hermetically (fake LLM endpoint, stubbed Wikipedia HTTP) and passes under `pytest`; a separate manual smoke procedure against live Ollama + OpenRouter + Wikipedia is documented.

## Out of Scope

- Calendar tools, web-search-beyond-Wikipedia, and any general/multi-tool layer — Phase 0 ships exactly one tool.
- The voice cascade: wake-word detection, STT, VAD/recorder endpointing, TTS, AEC, barge-in, and turn-detection.
- Token streaming, end to end.
- Building the Layer 2 index itself (Graphiti/FalkorDB or any other indexer) — Phase 0 defines and stubs the read seam only.
- The persona character (Calcifer's voice/tone/revoice behavior) — Phase 0 wires a no-op seam only.
- LangGraph or any other agent/graph orchestration framework.
- Discord or any chat-platform integration.
- Multi-user support of any kind.

## Open Questions

None.
