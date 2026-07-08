---
generated: 2026-07-07T22:56:23Z
commit: 58fb2ba9bbeefc5db7d530261bcb3450573048fa
agent: fledge-forager
fledge_version: unknown
---

# Architecture

Offline-first voice assistant ("Calcifer") plus a separate Textual monitor TUI. The runtime is a single async loop that turns spoken audio into a routed skill action and speaks a persona-flavored reply. Everything is interface-per-capability: the pipeline depends only on ABCs, and one composition root (`assistant/app.py`) constructs and injects concrete providers. This document describes the runtime flow, the seams that keep the dependency graph acyclic, and how the three most recent plumages (self-update, AI-first search, persona revoice) thread through it.

## The pipeline loop

`assistant/core/pipeline.py:VoicePipeline` is the state machine:

> wake word → record (VAD) → transcribe (STT) → route (orchestrator) → skill → speak (TTS)

- **Wake** — `wake/livekit_detector.py:LivekitWakeDetector.process(frame)` yields a `WakeEvent(name, score)` after `trigger_frames` consecutive high-scoring frames over a rolling 2s window; the model artifact is `models/wake/calcifer.onnx` (`wake/registry.py` derives spoken phrases from the manifest).
- **Record** — `audio/recorder.py:VadRecorder` collects PCM until trailing silence, timeout, or cap; `audio/mic_hub.py:MicHub` fans frames to the recorder plus a synchronous *tap* so wake detection continues during playback (barge-in). Optional AEC (`audio/aec.py:SpeexEchoCanceller`) subtracts speaker output from the mic.
- **Transcribe** — `stt/faster_whisper_stt.py:FasterWhisperSTT.transcribe(bytes)`; near-silent hallucinations are filtered by an RMS gate in the pipeline.
- **Route** — `core/orchestrator.py:Orchestrator.handle()` runs the tool-calling loop (see below).
- **Speak** — the pipeline's `_speak(text, voiced=False)` choke point runs text through `core/revoice.py:Revoicer` (unless already `voiced`) then `tts/piper_tts.py:PiperTTS.synthesize()`. Output is serialized against capture by `core/arbiter.py:AudioArbiter` (a single async lock).

All capability methods are `async`; blocking native work (Whisper, Piper, Speex, PortAudio) is pushed to `asyncio.to_thread()` or callback threads.

## Routing: the orchestrator tool-calling loop

`core/orchestrator.py:Orchestrator` is the router. It exposes each skill intent as an OpenAI-style tool schema via `SkillRegistry.tool_schemas()` and asks the LLM to either call one tool (its arguments populate `Intent.slots`) or answer directly. Supports `tool_mode` = native/json/auto, a `max_tool_rounds` cap, and an optional two-stage **verify loop** (`core/verify.py`): a *pre* stage reviews the tool pick + args and a *post* stage reviews the drafted answer, each able to approve, reject, or rewrite. Any LLM/JSON failure or `turn_timeout_s` expiry degrades to the `default=True` skill (`skills/general.py:GeneralSkill`), which itself handles the offline case with a spoken canned message. Routing never hard-codes skill names.

## Composition root

`assistant/app.py` is the only wiring point (`_run()` async composition; `main()` entrypoint). It reads `Config`, selects audio devices, constructs every concrete implementation, wires shared state, boots subsystems concurrently via `asyncio.gather()` (pipeline, `ReminderScheduler`, `CalendarWatcher`, `ControlChannel`), and runs graceful boot health checks. Components receive primitive/config values, never the whole `Config` object, so they stay unit-testable. Secrets (`api_key`, calendar ids) are masked in the logged config dump.

## Interface-per-capability seams

Each capability is a package with a `base.py` ABC and concrete implementations beside it: `wake/`, `stt/`, `tts/`, `llm/`, `audio/`, `search/`, `weather/`, `calendar/`, `nlu/`, plus `scheduling/` and `storage/`. `sync/` and `connectivity/` are deliberate no-op stub ABCs reserving future seams (Phase-6 connectivity routing, calendar upstream sync) — not dead code. **The pipeline imports only ABCs; concrete types appear only in `app.py`.**

`core/events.py` holds the shared dataclasses (`WakeEvent`, `Turn`, `Command`, `ToolCall`, `Intent`, `SkillResult`) that flow between stages. They live in `core/` precisely so capability packages can pass them without importing each other — this is the rule that keeps the graph acyclic.

## Shared runtime state

`core/standdown.py:StandDown` is a single "stop listening" flag built in `app.py` and threaded into the pipeline, reminder scheduler, calendar watcher, control channel, and `StandDownSkill`. Consumers poll `.active` on their own tick (no background timer), so a timed stand-down simply expires and a daemon restart clears it. `core/state.py:StateEmitter` writes `@@STATE {json}` lines to stdout that the TUI reads (`NullStateEmitter` on an interactive terminal). `core/control.py:ControlChannel` reads stdin commands (TEXT, SET, SAY, LISTEN, CANCEL, STOP, RESUME) from the TUI.

## The LLM path (first-class — the next feature targets it)

The LLM layer (`assistant/llm/`) sits behind `base.py:LLMProvider` (async `complete` / `chat` / `chat_tools` / `health` / `aclose`, returning `ChatResponse{content, tool_calls}`). Three concrete providers:

- `ollama_provider.py:OllamaProvider` — local Ollama (`/api/generate`, `/api/chat`); health checks that the specific model is pulled; honors a `think` flag (suppresses reasoning for JSON output).
- `opencode_zen_provider.py:OpenCodeZenProvider` — remote OpenAI-compatible `/chat/completions` gateway; retry/backoff with jitter on 429/5xx/transport, never on 4xx-auth; raises `LLMResponseError(retryable: bool)` on malformed/empty 200s; health only probes reachability. **Landed after PLM-002; the newest provider.**
- `fallback_provider.py:FallbackLLMProvider` — wraps a primary and a fallback; catches any primary exception and retries on the fallback (empty responses do *not* trigger fallback — the orchestrator handles those). `health()` ORs both.

`app.py:_build_llm` / `_build_one_llm` is the dispatch: `provider == "opencode-zen"` → `OpenCodeZenProvider`, otherwise `OllamaProvider`; wrapped in `FallbackLLMProvider` when `LlmConfig.fallback` is set and differs from the primary. The boot health check seeds the `Revoicer` so a down LLM doesn't add latency to first replies. See `data-model.md` for the full `LlmConfig`, and `testing.md` for the httpx.MockTransport wire/guard seams.

## Recent plumages threaded through the architecture

- **PLM-001 self-update / restart-in-place** — `skills/update.py:UpdateSkill` does a two-phase confirm, then sets `SkillResult.restart=True`; the pipeline honors it *after* `_speak()` finishes so the sign-off is audible, then `core/selfupdate.py:restart_in_place()` does `os.execv` (same PID, fresh interpreter loads on-disk code). The TUI `DaemonSupervisor` survives the re-exec (pdeathsig).
- **PLM-002 AI-first web search** — `search/` gained keyed AI providers `TavilySearch` (synthesized answer) and `ExaSearch` (semantic highlights) alongside keyless `WikipediaSearch`/`DdgsSearch`; `search/multi.py:MultiSearch` fans out concurrently, round-robin merges, dedupes by URL. `skills/web_search.py:WebSearchSkill` runs an agentic refine→search→assess loop that classifies query type (factual→Tavily, semantic→Exa) and falls back to the keyless tier with a spoken notice.
- **PLM-003 persona-flavored revoice** — `core/revoice.py:Revoicer` restyles every unvoiced reply at the `_speak` choke point (circuit breaker, digit-preservation guard, bounded timeout). `SkillResult.voiced=True` marks already-persona-flavored text to bypass. `core/persona.py:canned()` supplies LLM-free template lines for error/offline paths. `ReminderScheduler` and `CalendarWatcher` also route announcements through the revoicer. Invariant: routing/verify *decision* prompts stay persona-free; persona appears only on spoken output.

## The monitor TUI (one-directional dependency)

`tui/` is a top-level sibling package (`python -m tui`) that supervises the daemon as a child process over the stdin control channel and reads its stdout log/state feed. It imports only `assistant.core.config.Config` and `assistant.wake.registry` — never the pipeline, skills, or native deps. **Nothing under `assistant/` may import `tui`.** Its deployment target is the Pi 5's 320×480 portrait touchscreen (~40×30 cells), touch-only; every screen must fit 40 columns (enforced by `tests/test_tui_screens.py`).

## Offline-first principle

Local implementations are the guaranteed path; remote/cloud (OpenCode Zen, Tavily, Exa, Google Calendar) always sits behind an interface with a local fallback. Providers health-check at boot and degrade with a logged warning rather than crashing. Config is the single source of truth (`core/config.py`), so the Raspberry Pi 5 deployment is config-only.

## Open Questions

- `FallbackLLMProvider` holds both primary and fallback provider instances simultaneously (each with its own pooled httpx client) — connection/memory cost is paid whether or not the fallback is ever used.
- `Orchestrator.delegate_direct_answers` implies two modes for no-tool answers (passthrough vs. re-voice through the default skill); the production setting isn't visible outside `app.py`.
- Whether a daemon restart after *broken* on-disk code surfaces a distinct "update failed" state to the TUI vs. a generic stopped-daemon state (flagged in PLM-001 as a safety follow-up).
