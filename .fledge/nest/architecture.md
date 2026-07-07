---
generated: 2026-07-07T02:45:41Z
commit: 8d180f04862c48fdddc61804b81dafcd0f620344
agent: fledge-forager
fledge_version: unknown
---

# Architecture

Calcifer is an offline-first voice assistant daemon plus a separate monitor TUI. This document describes how the runtime is wired, the seams that matter for extending it, and how the pieces relate. It pays special attention to the seams a "self-update / restart-in-place" feature would touch: the confirm-then-act reply seam, the persona/sign-off layer, the composition root, and the daemon supervision lifecycle.

## The two top-level packages

- `assistant/` — the daemon. Run as `python -m assistant.app`. Contains the whole voice pipeline, capabilities, skills, and orchestration.
- `tui/` — the monitor UI (Textual). Run as `python -m tui`. It supervises the daemon as a child process. **The dependency is strictly one-directional (`tui` → `assistant`) and narrow**: the TUI imports only `assistant.core.config.Config` and `assistant.wake.registry` — never the pipeline, skills, LLM, or native deps (`tui/app.py`, `tui/supervisor.py`; rule stated in `CLAUDE.md`). Nothing under `assistant/` may import `tui`.

## The pipeline

The runtime is one async loop in `assistant/core/pipeline.py:VoicePipeline.run()`:

> wake word → record (VAD) → transcribe (STT) → orchestrate/route → skill → speak (TTS)

`VoicePipeline` depends only on the capability ABCs (`WakeDetector`, `SpeechToText`, `LLMProvider`, `TextToSpeech`, `Skill`, `AudioIn`/`AudioOut`), never on concrete providers (`assistant/core/pipeline.py`). Cross-stage records flow through the shared dataclasses in `assistant/core/events.py` (`WakeEvent`, `Turn`, `Command`, `ToolCall`, `Intent`, `SkillResult`) — these live in `core/` so capability packages never import each other, keeping the dependency graph acyclic.

Beyond the base loop, the pipeline implements: multi-turn conversation with follow-up capture inside `followup_window_ms` (no wake word required), a barge-in gate (user speaks over the reply → playback cut, mic reopens without ack), silence/hallucination hardening, and a post-reply **continuation decision** (`_decide_continuation()`) where the LLM chooses `listen`/`confirm`/`end` while the reply is still being spoken; it degrades to silent `listen` when the LLM is offline (`assistant/core/pipeline.py`).

## Interface-per-capability

Each capability is a package with an ABC in `base.py` and concrete implementation(s) beside it: `wake/` (`LivekitWakeDetector`), `stt/` (`FasterWhisperSTT`), `llm/` (`OllamaProvider`), `tts/` (`PiperTTS`), `audio/` (`SoundDeviceIn/Out`, `MicHub`, `VadRecorder`), `search/` (`MultiSearch` over `DdgsSearch` + `WikipediaSearch`), `weather/` (`OpenMeteoWeather`), `calendar/` (`GoogleCalendar`). Cross-cutting runtime services live in `scheduling/` (`ReminderScheduler`, `CalendarWatcher`) and `storage/` (SQLite `ReminderStore`, `CalendarStateStore`). `sync/` and `connectivity/` are **deliberate stub seams** for future capabilities, not dead code (`assistant/sync/base.py`, `assistant/connectivity/base.py`).

Remote is an optional accelerator, never a hard dependency: providers health-check at boot and degrade with a logged warning rather than crashing (`OllamaProvider.health()`, boot checks in `assistant/app.py`).

## Composition root: app.py

`assistant/app.py` is the only wiring point. `_run(config, devices)` reads `Config`, selects audio devices, health-checks Ollama and Google Calendar, constructs every concrete provider and skill, registers skills on a `SkillRegistry` (marking `GeneralSkill` as `default=True`), injects everything into `VoicePipeline`, and runs `pipeline.run()`, `scheduler.run()`, `control.run()`, and optional `calendar_watcher.run()` concurrently via `asyncio.gather(...)` with resource cleanup in `finally` (`assistant/app.py`). Construction-time choices (which skills, the default skill, model paths) live here, not inside components. `main()` wraps `_run` and catches `KeyboardInterrupt` — there are currently **no SIGHUP/SIGUSR/SIGTERM handlers and no re-exec logic** (`assistant/app.py`; corroborated by `assistant/core` scout).

## Orchestration and skills

Routing is not hard-coded. The orchestrator (`assistant/core/orchestrator.py:Orchestrator.handle()`) runs an LLM tool-calling loop: it exposes each skill intent as an OpenAI-style tool schema via `SkillRegistry.tool_schemas()`, and the LLM either calls one tool (its arguments populate `Intent.slots`) or answers directly. The loop is bounded by `max_tool_rounds` and a per-turn timeout; native Ollama tool-calling falls back to JSON-prompt coercion (`tool_mode="auto"`), and any LLM/JSON failure or timeout degrades to the `default=True` `GeneralSkill` (`assistant/core/orchestrator.py`, `assistant/skills/general.py`). A skill is one `Skill` subclass (`assistant/skills/base.py`) declaring `name` + `intents`, registered via `SkillRegistry.register(...)`. See `modules.md` and `entry-points.md`.

## Shared runtime state and audio coordination

- **StandDown** (`assistant/core/standdown.py`): a single "stop listening" instance built in `app.py` and threaded into the pipeline, reminder scheduler, calendar watcher, control channel, and `StandDownSkill`. Consumers poll `.active` on their own tick — there is **no background timer task**, so a timed stand-down simply expires and a daemon restart clears it.
- **AudioArbiter** (`assistant/core/arbiter.py`): a single async lock protecting the audio device so capture, TTS playback, and proactive announcements (reminders, calendar events) never collide. Proactive pollers serialize through `arbiter.hold(...)`.
- **StateEmitter** (`assistant/core/state.py`): a one-directional feed printing `@@STATE {json}` marker lines to stdout, which the TUI parses (`tui/logparse.py:parse_state`) to drive its Now screen. Suppressed on interactive TTYs.

## Daemon supervision and the restart lifecycle (self-update relevance)

The TUI's `DaemonSupervisor` (`tui/supervisor.py`) spawns `python -m assistant.app` as an asyncio subprocess, streams its stdout via `lines()`, writes commands to its stdin (the control channel), and does start/stop/restart with SIGTERM→SIGKILL. It uses Linux `prctl(PR_SET_PDEATHSIG)` to orphan-proof the child. Config changes are applied by (re)starting the child with `ASSISTANT_*` env overrides.

For a self-update that re-execs the daemon in place via `os.execv`:
- `os.execv` **replaces the process image while keeping the same PID and inherited file descriptors**. If the daemon's stdin/stdout pipes to the supervisor are preserved across the exec, the supervisor's child handle stays valid and the control/state channels survive the transition. The `tui` scout flagged an open question here (worried `lines()` would EOF); the mechanics of `os.execv` (same PID, same fds) mean a normal exit is what the supervisor detects, not a re-exec — but this needs verification against Python's fd-inheritance/CLOEXEC behavior for asyncio subprocess pipes.
- The **re-exec target differs by deployment** (`packaging/entrypoint.py`): source runs re-exec `sys.executable -m assistant.app`; a PyInstaller-frozen binary must re-exec the frozen binary path, and the frozen `entrypoint.py` does `chdir(sys._MEIPASS)` so `config.yaml` and relative model paths resolve — that chdir/env setup must survive the exec.

See `entry-points.md` for the confirm-then-act reply seam and sign-off flow, `modules.md` for the per-module map, and `dependencies.md` for the freeze/re-exec target details.

## Open Questions

- No re-exec/restart-in-place logic exists yet in `assistant/app.py`; the KeyboardInterrupt path is the only shutdown hook. A self-update needs a new seam (signal handler or control verb) plus arbiter coordination so the sign-off finishes speaking before exec (`assistant/core`, `assistant-app` scouts).
- Whether the TUI `DaemonSupervisor` correctly treats an `os.execv` re-exec as "still running" (same PID, preserved pipes) vs. reporting a spurious exit, and whether a `_restart()` racing an in-flight re-exec could SIGTERM the wrong PID (`tui`, `tests-tui` scouts).
