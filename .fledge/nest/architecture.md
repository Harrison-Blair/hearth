---
generated: 2026-07-15T23:27:05Z
commit: e41ba8a73a56364e7c3bb1acf1332cadab817e45
agent: fledge-forager
fledge_version: 0.5.5
---

# Architecture

Covers the runtime request path, the two-tier LLM brain, and the module seams that make `hearth` config-driven. Cross-references `hearth/*`.

`hearth` is an offline-first voice personal assistant, packaged as the `hearth` distribution (console entry point `hearth = hearth.app:main`, `pyproject.toml`). The current build is a **text-driven spine**: `hearth run` starts a single asyncio daemon; a localhost WebSocket "veneer" carries turns in as text and answers back out; a two-tier LLM orchestrator does the reasoning; an append-only sqlite event log records everything. Wake word, STT/TTS/VAD/AEC, and scheduling/calendar/weather/search are roadmap only — present as `pyproject` extras and (for wake word) an offline `training/` pipeline, but not wired into the runtime import graph.

## Request path

`Veneer` (`hearth/veneer/server.py`) → `Loop.run_turn` (`hearth/loop.py`) → `Router` (`hearth/brain/router.py`) → LLM backend (`hearth/brain/local.py` / `hearth/brain/remote.py`) → `EventLog` (`hearth/memory/log.py`).

`hearth/app.py::_run_daemon()` wires the object graph once at startup: loads `.env`, instantiates `Settings` (`hearth/config.py`), constructs `Router`, `EventLog`, `ToolRegistry` (`hearth/tools/registry.py`), `Loop`, and `Veneer`, then calls `veneer.serve(host, port)`. `main(argv)` is the CLI entry (`argparse`: `--version`, `run`), wrapping `_run_daemon()` in `asyncio.run`.

## The two-tier brain

Both tiers are named roles resolved to backends via `llm.tiers` config (`hearth/config.py::LLMTiers`, `LLMConfig.resolve_tier`):

- **`default` tier — local persona orchestrator.** Every turn is served by this tier (local Ollama by default), carrying the Calcifer persona system prompt (`hearth/persona.py`, `PersonaConfig.system_prompt`). It exposes exactly one tool, `consult_brain(query)`, gated per-turn on `Router.brain_available()` — preserving a local-only fallback when the remote tier is disabled or unhealthy.
- **`tool` tier — remote "brain".** `consult_brain` (`hearth/tools/consult.py::BrainConsult`) runs a *nested* ReAct loop on the `tool` tier (OpenRouter by default), kept in its lane by `persona.brain_guard_prompt` injected as the nested loop's first system message. It reaches real data tools — currently only Wikipedia (`hearth/tools/wikipedia.py`) via `ToolRegistry.dispatch` — and returns findings as an observation the orchestrator folds back into Calcifer's voice. `BrainConsult` degrades `BrainError`/timeout to a plain-text observation rather than propagating.

Both call sites share one ReAct engine: `run_react_rounds` in `hearth/loop.py` (Thought → Action → Observation, capped by `round_cap`, balanced start/end tool-activity emission even under timeout/cancellation — `CancelledError` is a `BaseException` and isn't swallowed by the inner `except Exception`). Do not duplicate this loop logic elsewhere.

## Key seams

- **`hearth/brain/`** — `base.py` holds the frozen `Brain` protocol and boundary types (`Message`, `ToolCall`, `ToolSpec`, `BrainResult`, `Capabilities`); `router.py::Router.select()` maps a tier role to a backend instance and returns a `Selection(brain, tier, backend_name, reason)`; `local.py` (Ollama-style) and `remote.py` (OpenRouter, Bearer auth) both build on shared OpenAI-compatible request/response logic in `openai_compat.py`; `errors.py::BrainError` normalizes backend failures into a client-safe `reason` plus internal `detail` (retries only on transient `httpx.TransportError`, never on timeout or `HTTPStatusError`).
- **`hearth/veneer/`** — the localhost control surface. `protocol.py::serialize` is a strict **whitelist**: only `type`/`turn_id`/`phase`/`label`/`text` cross the wire (forbidden keys: `query`, `arguments`, `observation`, `result`), so tool query/arguments/observation content can never leak to the client; unknown event types raise — fail loud. `server.py::Veneer.serve`/`_handle_connection` runs `Loop.run_turn` per WebSocket connection with a per-turn emit sink, disables `ping_interval` (idle localhost connections shouldn't false-close). `client.py` is a companion CLI client (`python -m hearth.veneer.client`) that offloads stdin reads to a thread so the event loop stays free for keepalive.
- **`hearth/memory/`** — `log.py::EventLog` is an append-only sqlite store (`append`, `read_session`; no update/delete); `reader.py::EventReader` is a read-only, cursor-based pull interface (`latest_cursor`, `read_since`) — the Layer-2 seam a future background indexer attaches to; `consumer.py` defines a `NoOpConsumer` reference implementation. Don't couple writers to the reader.
- **`hearth/transcript.py`** — optional per-session human-readable transcripts under `logs/transcripts/<session_id>.txt`, separate from the event log; best-effort (swallows `OSError`).
- **`hearth/persona.py`** — currently a no-op `restyle` stub (FTHR-011 placeholder); persona shaping is config (`system_prompt`, `brain_guard_prompt`) rather than code today.

## Config-driven-ness

Every device id, model path, and threshold lives in `config.yaml`/`default-config.yaml` (loaded via `pydantic-settings`; see `dependencies.md` and `entry-points.md`), which is deliberate: per `CLAUDE.md`, the Raspberry Pi 5 port is meant to be **config-only**, no code changes.

## Roadmap vs. wired (verified against source)

Confirmed by directory listing: `hearth/` contains only `app.py`, `brain/`, `config.py`, `events.py`, `logging_setup.py`, `loop.py`, `memory/`, `persona.py`, `tools/`, `transcript.py`, `veneer/` — **no** `wake/`, `stt/`, `tts/`, `vad/`, `aec/`, `scheduling/`, or `calendar/` package. The `training/` pipeline (see `domain.md`) exports `models/wake/calcifer.onnx`, but **nothing under `hearth/` imports or loads it** — it is inert until a future feather wires it in. (One scout report claimed a `hearth/wake/livekit_detector.py` consumer; this was checked against the actual directory listing and does not exist — corrected here.)

## Open Questions

- Whether `EventLog`'s sqlite connection has explicit thread-safety guards for a future concurrent Layer-2 reader (writes are autocommit, one transaction per `append()`) — not fully verified from source alone.
- Exact enforcement mechanism for the "secrets only in `.env`" rule (FTHR-015) — no schema validation currently prevents a stray key field in YAML.
