---
generated: 2026-07-17T06:36:02Z
commit: 2cf763f017cef0f330f2fb0df7157c947be1113a
agent: fledge-forager
fledge_version: 0.6.7
---

# Architecture

How hearth's runtime spine is wired together: the daemon startup sequence, the two-tier "brain" pattern, the veneer boundary, and the module dependency graph. Covers what actually runs today; the audio pipeline (wake/STT/TTS/VAD/AEC) and scheduling/calendar are roadmap only (extras + `training/`, not wired into `hearth/`).

## Request path (today)

`Veneer` (`hearth/veneer/server.py`, WebSocket, localhost `127.0.0.1:8765` by default) → `Loop.run_turn` (`hearth/loop.py`) → `Router` (`hearth/brain/router.py`) → LLM backend (`hearth/brain/local.py` / `remote.py`) → `EventLog` (`hearth/memory/log.py`). Text in, text out — no audio today.

## Daemon startup (`hearth/app.py`)

`main()` parses `--version` / `run` and dispatches to the async `_run_daemon()`, which wires the object graph in this order (`hearth-core.md`):

1. Load `.env` (`python-dotenv`), instantiate `Settings` (`hearth/config.py`).
2. `setup_logging()` (idempotent, guards against duplicate handler stacking).
3. Build one `httpx.AsyncClient` per configured LLM backend, plus one tool client (`_build_llm_clients()`).
4. `Router(config.llm, clients)` — LLM tier→backend wiring.
5. `EventLog(config.storage.db_path)` — sqlite append-only store.
6. `ToolRegistry(config.tool, tool_client)` — registers Wikipedia if enabled.
7. `BrainConsult(router, tool_registry, event_log, ...)` — the nested ReAct tool.
8. `Loop(router, event_log, brain_consult, config, ...)`.
9. `Veneer(loop, event_log, config)` → `Veneer.serve()`, runs until cancelled; httpx clients closed on shutdown.

Frozen boundary: `Loop` never imports `Router`/`EventLog`/`Veneer` directly for wire purposes — it talks to the client only through an injected `EventSink` callable and `ToolActivity` events (`hearth/events.py`). This is the seam that keeps internal tool detail off the wire.

## The two-tier brain (the defining pattern)

- **Local persona orchestrator** (tier `"default"`, `hearth/brain/local.py` → `LocalBackend`, Ollama-style) — every turn is served by this tier, carrying the persona system prompt (persona name "Vesta" in config/tests; "Calcifer" is the project's wake word, referenced in the persona prompt, not the orchestrator's own name — see `domain.md` for the reconciled terminology). It exposes exactly one tool, `consult_brain(query)`, gated per-turn on `Router.brain_available()`.
- **Remote "brain"** (tier `"tool"`, `hearth/brain/remote.py` → `RemoteBackend`, OpenAI-compatible, OpenRouter by default) — `consult_brain` (`hearth/tools/consult.py::BrainConsult`) runs a *nested* ReAct loop on this tier, kept in its lane by `persona.brain_guard_prompt` (injected as the first system message — `test_brain_guard.py`). It reaches real data tools — currently Wikipedia (`hearth/tools/wikipedia.py`) — via `ToolRegistry.dispatch`, and returns findings as an observation the orchestrator folds back into its own voice.
- Both call sites — the top-level orchestrator turn in `Loop.run_turn` and the nested consult in `BrainConsult.__call__` — share **one** ReAct engine: `run_react_rounds()` in `hearth/loop.py` (Thought→Action→Observation, round-capped by `agent.max_tool_rounds` / `agent.max_consult_rounds`). Do not duplicate this logic.
- `Router.select(tier_override=None)` deterministically resolves a tier to a `Brain` (protocol in `hearth/brain/base.py`); `tier_override="tool"` is how `BrainConsult` reaches the remote tier.
- Backend failures normalize to `BrainError(reason, detail)` (`hearth/brain/errors.py`) — `reason` is client-safe, `detail` is internal-only and never includes API keys. Both call sites catch `BrainError` and degrade to a plain-text observation rather than crashing the turn.

## The veneer boundary (security/isolation seam)

`hearth/veneer/protocol.py::serialize()` is a **structural whitelist**: it accepts a `ToolActivity` (`turn_id`, `phase`, `label`) and copies only those fields plus `type` onto the wire; unknown event types raise `TypeError` — fail loud, never leak. `curate_error()` similarly whitelists only `BrainError.reason` (or a generic fallback) for the client; full internal detail is logged server-side only, never sent. This is verified directly: `tests/test_veneer.py::test_no_tool_internals_cross_boundary` asserts forbidden keys (`query`, `arguments`, `observation`, `result`) never appear in any outbound message.

`Veneer` (`hearth/veneer/server.py`) is a single WebSocket server class: one session per connection (ephemeral UUID), one turn processed at a time per connection (each inbound frame fully awaited — including all its emitted messages — before the next is read), no ping keepalive (`ping_interval=None`, deliberate — this is a localhost control surface that legitimately idles between turns). `hearth/veneer/client.py` is a minimal stdin/stdout dev/test client, not a production consumer.

**This module currently assumes it is "the" veneer** — naming that a future rename to `chat` (alongside a new audio veneer) will need to touch: the `Veneer` class itself, `VeneerConfig`/`Settings.veneer` in `hearth/config.py`, the `HEARTH_VENEER__HOST`/`HEARTH_VENEER__PORT` env vars, the `hearth/veneer/` package path, the `"veneer"` string logged as an EventLog provenance tag (`server.py`), and imports across `hearth/app.py` and the veneer test files. See `modules.md` for the full reference list.

## Module dependency graph

```
hearth/app.py (daemon wiring)
  ├─ hearth/config.py         (Settings — no internal deps)
  ├─ hearth/logging_setup.py  (stdlib only)
  ├─ hearth/brain/router.py   ──┬─ hearth/brain/local.py  ─┐
  │                             └─ hearth/brain/remote.py ─┼─ hearth/brain/openai_compat.py
  │                                                          └─ hearth/brain/base.py, errors.py
  ├─ hearth/memory/log.py     (EventLog — sqlite, no internal deps)
  ├─ hearth/tools/registry.py ─── hearth/tools/wikipedia.py
  ├─ hearth/tools/consult.py  ─┬─ hearth/brain/router.py (tier_override="tool")
  │                            └─ hearth/loop.py::run_react_rounds (shared engine)
  ├─ hearth/loop.py           ─┬─ hearth/brain/* (Message, BrainResult, BrainError)
  │                            ├─ hearth/tools/consult.py (BrainConsult, dispatch)
  │                            ├─ hearth/persona.py (restyle, currently no-op)
  │                            └─ hearth/transcript.py (Transcript.append, best-effort)
  └─ hearth/veneer/server.py  ─── hearth/loop.py::Loop.run_turn (only touchpoint)
                                  hearth/memory/log.py (EventLog, for error logging)
                                  hearth/brain/errors.py (BrainError, for curate_error)
                                  hearth/events.py (ToolActivity, EventSink — shared boundary type)

hearth/memory/reader.py  (EventReader — read-only cursor pull; Layer-2 seam, no current consumer)
hearth/memory/consumer.py (Layer2Consumer protocol + NoOpConsumer stub — proof-of-concept only)
```

`hearth/veneer/` never imports `hearth/brain/` directly — it only reaches `Loop.run_turn` and catches `BrainError` for error curation. This is the intended isolation: veneer surfaces talk to the engine only through `Loop`, never around it.

## Roadmap vs. wired (repo-wide)

- **Wired**: `hearth run` daemon, veneer WebSocket surface, two-tier LLM orchestrator, Wikipedia tool, sqlite event log, EventReader Layer-2 seam (unconsumed).
- **Not wired**: audio pipeline (wake word, STT, TTS, VAD, AEC) — exists only as `pyproject.toml` extras and the standalone `training/` pipeline producing `.onnx` artifacts (`models/wake/vesta.onnx`, 960,600 bytes) that nothing in `hearth/` currently loads. Scheduling/calendar/weather/search are extras only, no runtime code.
- `Settings` (`hearth/config.py`) has exactly 8 sections today: `llm`, `veneer`, `tool`, `agent`, `persona`, `conversation`, `storage`, `logging`. No `audio`/`wake`/`stt`/`tts`/`verify`/`scheduling`/`calendar` sections exist yet — adding the audio veneer means extending this schema.

## Open Questions

- How does `training/` eventually integrate with the runtime to load and use `.onnx` models — is there a planned `hearth/wake/` or similar consumer module?
- What is the current state of the audio pipeline beyond training infra and exported models (`sounddevice`/`numpy` are base runtime deps already, per `root.md`, but unused today)?
- Is there an actual scheduler/background consumer wired to `EventReader`, or is `Layer2Consumer.pull_once()` purely proof-of-concept (`hearth-memory-tools.md`)?
