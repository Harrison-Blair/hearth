---
id: PLM-002
title: "hearth: local-orchestrator topology and reliability hardening"
status: fledged
priority: P1
authored: 2026-07-11T02:43:21Z
agent: fledge-orchestrate/planning
fledge_version: 0.3.4
---

# PLM-002: hearth: local-orchestrator topology and reliability hardening

## Context
Driving `python -m hearth.veneer.client` surfaced four defects that share one root cause — the pipeline is wired backwards from how it's meant to work:
1. **Identity leak** — "who are you" → "I'm ChatGPT … developed by OpenAI LLC."
2. **Tool-turn crash** — "search wikipedia for flowers" prints partial output then dies with the opaque `error: the turn failed`.
3. **No logging** — `LoggingConfig` exists but is wired to nothing; unconfigured root logger dumps raw `websockets` tracebacks to stderr.
4. **WebSocket fragility** — a client disconnect raises an unhandled traceback.

Today `Router.select` routes the whole turn to the **remote** tier whenever tools exist (`router.py:47-53`, `loop.py:62`), so the remote model talks to the user directly and leaks its base identity. This plumage reorients the topology: the **local** model (qwen3, Calcifer persona) becomes the front-facing orchestrator that decides per-turn whether to consult a **remote** "brain" (OpenRouter) via a single `consult_brain(query)` tool; the brain runs its own nested ReAct loop over the real data tools (wikipedia) and returns findings; local themes the answer in persona. This fixes the identity leak structurally (the remote model never addresses the user) and gives a natural home for the crash-hardening, logging, and websocket-robustness fixes that ride along.

## User Stories
- As a user talking to Calcifer, I want every response to consistently be "Calcifer" (never an underlying model's raw identity), so that the persona feels coherent.
- As a user asking a question that needs external data (e.g. "search wikipedia for flowers"), I want the assistant to fetch and incorporate that data without crashing the turn.
- As an operator running hearth unattended, I want rotating file logs and a per-session human-readable transcript covering both the orchestrator and any brain consultations, so that I can diagnose issues after the fact instead of relying on stderr.
- As an operator, I want a client disconnect or a backend failure to degrade gracefully (curated error surfaced to the client, or a graceful in-persona apology) rather than crash the server or produce an opaque error.
- As an operator with the remote brain disabled, I want the assistant to keep working local-only (no `consult_brain` offered, no crash), preserving PLM-001's fallback behavior.

## Functional Criteria
1. FC-1: The top-level turn is always served first by the local/default tier, carrying a persona (Calcifer) system prompt; the remote tier is never the first responder to the user.
2. FC-2: The local orchestrator has exactly one tool, `consult_brain(query)`, offered only when the remote brain is available; calling it runs a **nested** ReAct loop on the remote tier over the existing data tools (currently `wikipedia_search`), and returns findings as an observation to the orchestrator.
3. FC-3: `wikipedia_search` (and any future data tool) is invocable only from inside the nested brain loop, never directly by the orchestrator.
4. FC-4: The remote brain's nested loop carries a guard prompt instructing it not to assert an identity or address the user; this is config-driven, not hardcoded.
5. FC-5: Errors from the remote backend (HTTP failure, malformed response body, malformed tool-call arguments) are caught and converted to a typed, curated error rather than propagating a raw exception; a consult-time failure degrades to a graceful in-persona observation instead of crashing the turn.
6. FC-6: When the remote brain is unavailable, `consult_brain` is not offered and every turn is served local-only (no crash, no missing-tool error).
7. FC-7: Rotating file logging is configured at daemon startup (not import time), captures records for both the orchestrator (local) model and each consultation's remote model, and also captures the `websockets` library's logger (no raw tracebacks to stderr).
8. FC-8: When transcripts are enabled, a per-session human-readable file records the user's text, the final answer, and each consult query/findings, in order.
9. FC-9: A `BrainError` surfaced out of a turn reaches the veneer client as a curated, client-safe reason (not the generic "the turn failed"); non-`BrainError` failures still show the generic message while the real detail is written to the EventLog. The existing content privacy whitelist (`serialize()`) is unchanged.
10. FC-10: A client disconnect mid-turn (`websockets.ConnectionClosed`) is handled cleanly; the server continues serving other connections.

## Acceptance Criteria
- [x] AC-1: Asking "who are you" produces a Calcifer-voiced answer with no ChatGPT/OpenAI identity leak, and the routing decision shows the turn was served local-only (structural proof, not a prompt patch).
- [x] AC-2: Asking a question requiring external data (e.g. "search wikipedia for flowers") completes without crashing, invoking `consult_brain` then `wikipedia_search` inside the nested loop, and returns a persona-voiced answer incorporating the retrieved facts.
- [x] AC-3: A forced remote-backend failure during a consult degrades gracefully — the orchestrator still produces a persona answer acknowledging it couldn't reach external data — rather than crashing the turn.
- [x] AC-4: A killed/unreachable local backend surfaces the curated `BrainError` reason to the veneer client, not "the turn failed".
- [x] AC-5: With the remote brain disabled, every turn is served local-only, `consult_brain` is never offered, and no turn crashes (PLM-001 fallback preserved).
- [x] AC-6: `logs/hearth.log` (rotating) and, when enabled, `logs/transcripts/<session>.txt` both show records/lines for the orchestrator's local model and any consultation's remote model, per turn.
- [x] AC-7: A client Ctrl-C mid-turn produces a clean `ConnectionClosed` log entry; the server keeps serving other connections afterward.
- [x] AC-8: All 5 feathers (FTHR-008..012) are fledged with every AC box checked.

## Out of Scope
- `persona.restyle` remains a no-op — theming falls out for free from the local model's persona-conditioned answer; a dedicated restyle pass is not built.
- No new data tools are added — only `wikipedia_search` moves to brain-side; other tool additions are separate future work.
- No changes to the STT/TTS/wake/VAD pipeline stages, calendar/weather/scheduling integrations, or AEC/barge-in.
- No changes to the content privacy whitelist in `serialize()` — only which curated string reaches it.
- Tuning of round-cap/timeout defaults (`max_consult_rounds=3`, `consult_timeout_s=30.0`, `turn_timeout_s=45s`) against real Ollama+OpenRouter latency is flagged as a follow-up manual-tuning concern, not a blocking acceptance criterion.

## Open Questions
None — all decisions were resolved in the prior planning conversation (see plan file `new-issues-arrisen-i-virtual-bachman.md`).
