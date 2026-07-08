---
generated: 2026-07-08T00:34:07Z
commit: 0a67e65dc3d33b2e9c911f1296eef515124fa678
agent: fledge-forager
fledge_version: unknown
---

# Architecture

An offline-first voice assistant ("Calcifer") that listens for a wake word, transcribes a command, routes it to a skill via an LLM tool-calling loop, and speaks the reply. Everything that can run locally does; remote services (LLM gateways, web search, weather, calendar) are optional accelerators behind interfaces with local fallbacks. Deployment target is a Raspberry Pi 5; development/verification happens on Linux desktop first.

## The pipeline

The single async loop lives in `assistant/core/pipeline.py:VoicePipeline.run()`:

> wake word → record (VAD) → transcribe (STT) → route (orchestrator) → skill → speak (TTS)

`VoicePipeline` depends only on capability ABCs (`assistant/audio/base.py:AudioIn`/`AudioOut`, `assistant/stt/base.py:SpeechToText`, `assistant/tts/base.py:TextToSpeech`, `assistant/wake/base.py:WakeDetector`, `assistant/llm/base.py:LLMProvider`); it never imports a concrete provider. Alternate entry points into the same route/speak path: `submit_text()` (typed command from the TUI), `request_listen()` (tap-to-listen, skip wake), `cancel()`.

## Interface-per-capability

Each capability is its own package with an ABC in `base.py` and concrete implementation(s) beside it: `wake/`, `stt/`, `llm/`, `tts/`, `nlu/`, `audio/`, `search/`, `weather/`, `calendar/`, plus `scheduling/` and `storage/`. `sync/` and `connectivity/` are deliberate stub seams (`assistant/sync/base.py:SyncAdapter`, `assistant/connectivity/base.py:ConnectivityService`/`ProviderRouter`) — intentional future contracts, not dead code. Adding or swapping an implementation means coding against the `base.py` ABC; the pipeline must never reach for a concrete type.

## Composition root: app.py

`assistant/app.py` is the only wiring point. `main()` builds `Config()`, sets up logging, selects audio devices; `_run(config, devices)` constructs every concrete implementation (`PiperTTS`, `LivekitWakeDetector`, `FasterWhisperSTT`, LLM providers, skills, search/weather/calendar providers, schedulers, stores) and injects them into `VoicePipeline`. Construction-time choices (which skills, the default skill, which LLM provider) live here, not inside components. Concurrent tasks run via `asyncio.gather(pipeline.run(), scheduler.run(), control.run(), [calendar_watcher.run()])`; cleanup `.aclose()`/`.close()` in a finally block.

## LLM provider path (post-PLM-004)

The LLM layer is a vendor-neutral OpenAI-compatible gateway plus a local Ollama path, composed with an exception-based fallback. See `entry-points.md` and `data-model.md` for full detail. Key files:

- `assistant/llm/base.py` — `LLMProvider` ABC: `complete()`, `chat()`, `chat_tools()`, `health()`, `aclose()`; `ChatResponse(content, tool_calls)`.
- `assistant/llm/openai_compatible_provider.py` — `OpenAICompatibleProvider` (generic `/chat/completions`) + the `GATEWAYS` table mapping provider name → `{base_url, extra_headers}`. Current entries: `opencode-zen` (`https://opencode.ai/zen/v1`) and `openrouter` (`https://openrouter.ai/api/v1`). `OpenCodeZenProvider`/`opencode_zen_provider.py` no longer exist — the generic class replaced them (PLM-004 / FTHR-010).
- `assistant/llm/ollama_provider.py` — `OllamaProvider`, the local/offline path and default fallback.
- `assistant/llm/fallback_provider.py` — `FallbackLLMProvider(primary, fallback)`; delegates to primary and only falls back on exception (a valid-but-empty response does not fall back).
- `assistant/app.py:_build_llm`/`_build_one_llm`/`_gateway_base_url`/`_llm_unhealthy_warning` — resolve `LlmConfig` into providers, health-check at boot, and log a vendor-neutral warning driven by `GATEWAYS[provider]` rather than hard-coded vendor checks.

Remote is never a hard dependency: providers health-check at boot (`await llm.health()`) and degrade with a logged warning rather than crashing.

## Routing: skills as plug-ins

Routing is a tool-calling loop in `assistant/core/orchestrator.py:Orchestrator.handle()`. Each skill (`assistant/skills/base.py:Skill` subclass) declares `name` + `intents`; `SkillRegistry.tool_schemas()` exposes every intent as an OpenAI-style function tool. The LLM either calls one tool (its arguments populate `Intent.slots`) or answers directly. Any LLM/JSON failure, unknown tool, tool-repeat-cap breach, or turn timeout degrades to the `default=True` skill (`GeneralSkill`), which handles the offline case with a spoken message. An optional pre/post **verify** loop (`assistant/core/verify.py`) can approve/rewrite/reject a tool pick or answer; it fails open (a `None` verdict approves). Routing never hard-codes skill names.

## Speech flavoring (persona)

Every spoken reply sounds like the Calcifer persona. `SkillResult.voiced` marks replies already persona-flavored (skip the revoicer); everything else is restyled live at the speak choke point by `assistant/core/revoice.py:Revoicer` (one LLM call, digit-preservation guard, circuit-breaker cooldown). LLM-free "canned" lines (`assistant/core/persona.py:canned()`) provide in-character error/offline text. Persona is applied only to spoken output — never to tool-decision, verify-decision, or routing prompts (enforced by `tests/test_speech_invariants.py`).

## Shared records and acyclic graph

`assistant/core/events.py` holds the dataclasses that flow between stages (`WakeEvent`, `Command`, `Intent`, `SkillResult`, `Turn`, `ToolCall`). They live in `core/` so capability packages can pass them without importing each other, keeping the dependency graph acyclic. `assistant/core/standdown.py:StandDown` is a single shared "stop listening" state, threaded into the pipeline, schedulers, watcher, and control channel; consumers poll `.active` on their own tick (no background timer).

## Proactive announcements

Two background loops speak unprompted: `assistant/scheduling/scheduler.py:ReminderScheduler` (fires due reminders/timers, catch-up summary on boot) and `assistant/scheduling/calendar_watcher.py:CalendarWatcher` (announces upcoming calendar events within a lead window, deduped across restarts). Both serialize audio through `assistant/core/arbiter.py:AudioArbiter` so announcements never collide with the capture/playback path or self-trigger the wake word.

## The monitor TUI (separate package)

`tui/` is a sibling top-level package (run with `python -m tui`) that supervises the daemon as a child process (`python -m assistant.app`) over a stdin control channel and parses its stdout (`@@STATE {json}` feed + log lines). It targets the Pi 5's 320×480 portrait display (~40×30 cells), touch-only. The dependency is strictly one-directional: `tui/` imports only `assistant.core.config.Config` and `assistant.wake.registry`; nothing under `assistant/` imports `tui`. This lets the daemon run headless while the TUI runs elsewhere.

## Configuration and secrets

`assistant/core/config.py` (pydantic-settings) is the single source of truth: `config.yaml` → typed `*Config` models, overridable by `ASSISTANT_*` env vars with `__` for nesting. Precedence is init args > env > `config.yaml` (`Config.settings_customise_sources`). Secrets (LLM/search API keys, calendar credentials) are separated from configuration and delivered via environment rather than committed YAML; the monitor TUI merges a `.env` file into the daemon's process environment at (re)start (`tui/envfile.py` + `tui/supervisor.py`) — the daemon's pydantic-settings does not itself load `.env`. See `conventions.md` and `data-model.md`.
