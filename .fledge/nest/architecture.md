---
generated: 2026-07-07T07:06:00Z
commit: 02f839d7a116780b02510c2d5b339c23c64a51f5
agent: fledge-forager
fledge_version: unknown
---

# Architecture

`personal-assistant` is an offline-first voice assistant for the Raspberry Pi 5 (and Linux desktops). It is two cooperating top-level packages — the daemon (`assistant/`) and a monitor TUI (`tui/`) — plus a wake-word training pipeline (`training/`) and packaging tooling. This document explains how the pieces fit; see `modules.md` for the per-directory map.

## The pipeline is one async loop

The runtime is a single async loop in `assistant/core/pipeline.py:VoicePipeline.run()`:

> wake word → record (VAD) → transcribe (STT) → route (orchestrator) → skill → speak (TTS)

Every pipeline-facing method is `async`; CPU-bound work (Whisper, Piper, Ollama) is pushed to `asyncio.to_thread()` so the loop stays responsive. The loop also handles follow-ups without a wake word, barge-in (wake spoken over the reply), continuation decisions (listen/confirm/end), sentence-by-sentence TTS streaming, and stand-down.

## Interface-per-capability

Each capability is a package with an ABC in `base.py` and concrete implementation(s) beside it. `VoicePipeline` and the skills depend only on the ABCs, never a concrete type:

- Voice I/O: `assistant/wake/base.py:WakeDetector`, `assistant/stt/base.py:SpeechToText`, `assistant/tts/base.py:TextToSpeech`, `assistant/audio/base.py:AudioIn`/`AudioOut`.
- Reasoning: `assistant/llm/base.py:LLMProvider` (with `assistant/nlu/timespec.py` for offline time parsing).
- Services: `assistant/search/base.py:SearchProvider`, `assistant/weather/base.py:WeatherProvider`, `assistant/calendar/base.py:CalendarProvider`.
- Stubs reserving future seams: `assistant/connectivity/base.py`, `assistant/sync/base.py` (`NoopSyncAdapter`).

## `app.py` is the only wiring point

`assistant/app.py` is the composition root. `main()` reads `Config`, selects audio devices, and `_run()` constructs every concrete implementation (`PiperTTS`, `LivekitWakeDetector`, `FasterWhisperSTT`, `OllamaProvider`, the skills, the `Orchestrator`, the schedulers, the control channel) and injects them into `VoicePipeline`. Construction-time choices — which skills, the default skill, provider fallback order — live here, not inside the components. Helper factories `_build_llm()`/`_build_one_llm()` and `_build_search()` isolate the provider-construction logic (`assistant/app.py:60–132`).

## Remote is an accelerator, never a hard dependency

Local implementations are the guaranteed path. Cloud/remote always sits behind an interface with a local fallback, and providers health-check at boot and degrade with a logged warning rather than crashing:

- LLM: `OllamaProvider` (local, default) primary; `OpenCodeZenProvider` (cloud, OpenAI-compatible) optional; `FallbackLLMProvider` wraps a primary→fallback chain (`assistant/llm/`). Exceptions from the primary trigger fallback; a valid-but-empty response does not (`FallbackLLMProvider`).
- Search: keyless `WikipediaSearch` (guaranteed) and `DdgsSearch` (DuckDuckGo scraper), composed by `MultiSearch` (`assistant/search/`).
- Calendar: `GoogleCalendar` is optional (`CalendarConfig.enabled`); its watcher and skill degrade per-call.
- `connectivity/` and `sync/` are deliberate stubs marking where remote acceleration will attach.

## Routing is an LLM tool-calling loop

Routing never hard-codes skill names. `assistant/core/orchestrator.py:Orchestrator.handle()` exposes each skill intent as a tool schema (`SkillRegistry.tool_schemas()`); the LLM either calls one tool (its arguments populate `Intent.slots`) or answers directly. Tool mode is native-Ollama → JSON coercion → offline general fallback (`AgentConfig.tool_mode`). Any LLM/JSON failure, unknown tool, repeated same-tool (`_TOOL_REPEAT_CAP`), or turn timeout degrades to the `default=True` skill, `GeneralSkill`, which itself handles the offline case with a spoken message.

Around the routing decision sits an optional **verification loop** (`assistant/core/verify.py`, `VerifyConfig`): a pre-stage reviews the tool pick + args, a post-stage reviews the drafted answer, each returning a `Verdict` of approve/rewrite/reject. It fails open (parse failure → approve) and, on a post-stage timeout, speaks the best draft rather than discarding it.

## Web-search capability (focus area)

The web-search path is the target of upcoming work (adding AI-first adapters such as Tavily/Exa/Brave), so its architecture is called out here:

- **Providers** (`assistant/search/`): `SearchProvider` ABC declares `async search(query, *, count) -> list[SearchResult]`, `async health() -> bool`, `async aclose()`. `DdgsSearch` wraps the synchronous `ddgs` package in `asyncio.to_thread`; `WikipediaSearch` calls the Wikipedia Action API over `httpx`. `MultiSearch` fans out to N providers concurrently (`asyncio.gather(return_exceptions=True)`), merges round-robin by rank, deduplicates by normalized URL (falling back to `source:title`), caps at `max_results`, and only raises if all providers fail.
- **Skill** (`assistant/skills/web_search.py:WebSearchSkill`): an agentic loop — refine query (LLM JSON) → search → assess (LLM JSON: `sufficient` → answer, else `new_query` + spoken `remark`) → answer/retry up to `max_rounds`. It speaks progress mid-turn via `core/speech.py:Speaker`, neutralizes untrusted snippet content against prompt injection (`_neutralize`, `<<<…>>>` fencing, `_ASSESS_SYSTEM` guard), and falls back to a plain LLM summary when assess fails.
- **Wiring** (`assistant/app.py:_build_search`): builds the provider list from `WebSearchConfig.providers`, constructs `MultiSearch`, and injects it plus `max_rounds`/`Speaker` into `WebSearchSkill`.
- **Config** (`assistant/core/config.py:WebSearchConfig`): `providers`, `language`, `region`, `result_count`, `max_results`, `timeout`, `max_snippet_chars`, `max_rounds`, `progress_updates`.

A new AI-first provider must implement the `SearchProvider` ABC (returning `SearchResult`s), be constructible from primitive config, be added to the `WebSearchConfig.providers` set and `_build_search` construction, and satisfy the existing test seams (see `testing.md`).

## Shared runtime state and the acyclic-graph rule

Cross-stage records (`WakeEvent`, `Command`, `Intent`, `SkillResult`, `Turn`, `ToolCall`) live in `assistant/core/events.py` so capability packages pass them without importing each other — this is what keeps the dependency graph acyclic. Two shared runtime objects are built in `app.py` and threaded everywhere they are needed:

- `assistant/core/standdown.py:StandDown` — a "stop listening" flag polled (`.active`) by the pipeline, reminder scheduler, calendar watcher, control channel, and `StandDownSkill`. No background timer: a timed stand-down simply expires and a restart clears it.
- `assistant/core/arbiter.py:AudioArbiter` — a single `asyncio.Lock` over the audio device; capture, TTS playback, and proactive announcements all acquire it so they never overlap.

Proactive subsystems `assistant/scheduling/scheduler.py:ReminderScheduler` and `calendar_watcher.py:CalendarWatcher` are independent poll loops that announce through the arbiter and respect stand-down.

## The TUI is a separate, one-directional supervisor

`tui/` is a Textual monitor targeting the Pi 5's **320×480 portrait touch display (~40×30 cells)**. It supervises the daemon as a child process (`python -m assistant.app`) over a stdin control channel (`tui/supervisor.py:DaemonSupervisor` ↔ `assistant/core/control.py:ControlChannel`; verbs TEXT/SET/SAY/LISTEN/CANCEL/STOP/RESUME) and reads its `@@STATE {json}` stdout feed. The dependency is strictly one-directional: `tui` imports only `assistant.core.config.Config` and `assistant.wake.registry`; nothing under `assistant/` imports `tui`.

## Config is the single source of truth

`assistant/core/config.py` (pydantic-settings) maps `config.yaml` → typed `*Config` models nested under a top-level `Config`. Any value is overridable by `ASSISTANT_*` env vars with `__` for nesting; precedence is init args > env > `config.yaml`. Every device id, model path, and threshold is config, so the Pi 5 deployment is config-only.

## Deployment

Two deployment shapes: source (`install.sh` → venv + per-capability extras → `python -m tui` or `python -m assistant.app`) and a PyInstaller single-file binary (`make release` → `packaging/build.sh` → `dist/assistant-$(uname -m)`), whose frozen entrypoint (`packaging/entrypoint.py`) chdir's to the bundle and redirects writable state to `$XDG_DATA_HOME/assistant/`. CI builds both x86_64 and aarch64 binaries on tag push (`.github/workflows/release.yml`).

## Open Questions

- The orchestrator docstring references a fuller ReAct pattern; the present loop is single-tool-call-per-round. Whether skills can trigger repeated tool calls within a turn is not fully settled (`assistant/core/orchestrator.py`, `assistant/app.py:80`).
- `Speaker` progress updates in `WebSearchSkill` are gated by `progress_updates`; whether `app.py` always injects a live `Speaker` in production vs. testing is not fully visible from wiring alone.
