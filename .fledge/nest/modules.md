---
generated: 2026-07-07T22:56:23Z
commit: 58fb2ba9bbeefc5db7d530261bcb3450573048fa
agent: fledge-forager
fledge_version: unknown
---

# Modules

Repo map organized by module. Two top-level Python packages — `assistant/` (the daemon) and `tui/` (the monitor) — plus training, packaging, planning specs, and docs. Each entry: purpose → key files → where to look.

## assistant/ (root wiring)

Purpose: composition root and provisioning entrypoints.
- `app.py` — the only wiring point; `_run()` composes and boots everything, `_build_llm`/`_build_one_llm` dispatch LLM providers, `main()` is the CLI entry. Config secrets masked in `_config_dump()`.
- `bootstrap.py` — `run(args)` provisioning (`assistant doctor`): ensures Ollama, model, STT cache.
- `__init__.py` — `__version__ = "0.1.0"`.

Look here for: how any component gets constructed and injected; provider dispatch; boot health checks; skill registration.

## assistant/core/ (pipeline & orchestration)

Purpose: the async main loop, router, shared types, config, and cross-cutting concerns.
- `pipeline.py` — `VoicePipeline`: wake→record→STT→route→skill→speak; barge-in, hallucination filter, incremental TTS via the `_speak` revoice seam.
- `orchestrator.py` — `Orchestrator`: LLM tool-calling loop, native/json/auto modes, `max_tool_rounds`, verify integration, fallback to `GeneralSkill`.
- `config.py` — pydantic-settings `Config` composing 18 sub-configs; precedence init > `ASSISTANT_*` env > `config.yaml`.
- `events.py` — shared dataclasses (`WakeEvent`, `Turn`, `Command`, `ToolCall`, `Intent`, `SkillResult`).
- `verify.py` — `Verdict` + `verify()` pre/post judgment loop (fail-open).
- `revoice.py` — `Revoicer`: live persona restyle, circuit breaker, digit guard (PLM-003).
- `persona.py` — Calcifer persona; `canned()` LLM-free line registry.
- `selfupdate.py` — `restart_in_place()` os.execv restart (PLM-001).
- `standdown.py` — `StandDown` shared mute state (poll `.active`).
- `arbiter.py` — `AudioArbiter` single audio lock. `state.py` — `StateEmitter` `@@STATE` feed. `control.py` — `ControlChannel` stdin verbs. `conversation.py` — bounded history. `speech.py` — `Speaker` progress synth. `logging.py` — JSONL logging + run pruning.

Look here for: the loop, routing, verify, config schema, persona/revoice, restart, shared records.

## assistant/llm/ (LLM providers — HIGH-PRIORITY, next feature area)

Purpose: LLM backends behind one ABC, with retry/fallback.
- `base.py` — `LLMProvider` ABC (`complete`/`chat`/`chat_tools`/`health`/`aclose`) + `ChatResponse{content, tool_calls}`.
- `ollama_provider.py` — `OllamaProvider`: local Ollama, model-pulled health, `think` flag.
- `opencode_zen_provider.py` — `OpenCodeZenProvider`: OpenAI-compatible `/chat/completions`, retry/backoff+jitter, `LLMResponseError(retryable)`, reachability health. Newest provider.
- `fallback_provider.py` — `FallbackLLMProvider`: primary→fallback wrapper; empty ≠ fallback; health ORs both.

Look here for: adding/modifying an LLM provider, wire format, retry/guard semantics, fallback behavior.

## assistant/skills/ (plug-in skills)

Purpose: intent handlers exposed as LLM tools.
- `base.py` — `Skill` ABC + `SkillRegistry` (`register(default=)`, `tool_schemas()`, `handle`/`handle_reply`).
- `general.py` — `GeneralSkill` (the `default` fallback; direct LLM answer, offline canned message).
- `web_search.py` — agentic refine→search→assess loop, keyed routing + keyless fallback, injection defense (PLM-002).
- `update.py` — two-phase self-restart confirm → `restart=True` (PLM-001).
- `calendar.py`, `reminder.py`, `timer.py`, `weather.py`, `clock.py`, `stand_down.py` — capability skills. `reminder`/`timer` share the reminder store via `kind`.

Look here for: how a skill declares intents/tools, slot handling, two-phase confirmations, persona flags.

## assistant/audio/ (audio I/O)

Purpose: capture, playback, device selection, echo cancellation, earcons.
- `base.py` (`AudioIn`/`AudioOut`), `sounddevice_io.py` (PortAudio), `mic_hub.py` (`MicHub` tap/fan-out), `recorder.py` (`VadRecorder`), `aec.py` (`SpeexEchoCanceller`, `build_aec`), `devices.py` (`select_devices`), `processing.py` (`normalize_peak`), `earcon.py` (tones/chimes).

Look here for: mic/speaker plumbing, VAD recording, barge-in tap, AEC, device resolution.

## assistant/stt/, tts/, wake/ (voice I/O edges)

Purpose: the acoustic edges.
- `stt/base.py` + `faster_whisper_stt.py:FasterWhisperSTT` (Whisper via CTranslate2, CPU).
- `tts/base.py` + `piper_tts.py:PiperTTS` (ONNX Piper; per-call `length_scale`).
- `wake/base.py` + `livekit_detector.py:LivekitWakeDetector` (rolling-window ONNX classifier) + `registry.py` (phrase derivation from manifest; imported by TUI).

Look here for: transcription config, TTS rate control, wake detection state machine, wake phrase lookup.

## assistant/search/, weather/, calendar/, nlu/ (capability providers)

Purpose: pluggable data providers with local fallbacks.
- `search/` — `base.py:SearchProvider`, `wikipedia.py`, `ddgs_provider.py` (keyless), `exa.py`/`tavily.py` (keyed AI, PLM-002), `multi.py:MultiSearch` (fan-out, dedupe).
- `weather/` — `base.py:WeatherProvider` + `open_meteo.py` (keyless forecast/geocode, WMO codes).
- `calendar/` — `base.py:CalendarProvider`/`CalendarEvent`, `google_calendar.py` (service-account), `blocklist.py:EventBlocklist`, `extraction.py` (LLM JSON event/management/reminder/block parsing).
- `nlu/timespec.py` — regex-first duration/recurrence parsing, LLM fallback for clock times; `humanize()`.

Look here for: search routing/providers, weather, calendar CRUD + LLM extraction, timespec parsing.

## assistant/scheduling/, storage/, connectivity/, sync/ (runtime)

Purpose: proactive announcements, persistence, reserved seams.
- `scheduling/scheduler.py:ReminderScheduler` (poll, retry budget, boot backlog coalesce, revoice), `calendar_watcher.py:CalendarWatcher` (lead-window announce, dedupe, blocklist, revoice).
- `storage/reminders.py:ReminderStore` (SQLite reminders/timers), `calendar_state.py:CalendarStateStore` (announced-events dedupe + blocked titles). Both sync SQLite, WAL mode.
- `connectivity/base.py`, `sync/base.py` — no-op stub ABCs (reserved seams, keep).

Look here for: reminder/timer/calendar announcement logic, DB schemas, standdown-aware polling.

## tui/ (monitor TUI — sibling package)

Purpose: Textual monitor supervising the daemon; Pi 5 320×480 portrait, touch-only.
- `app.py:AssistantTUI` (state owner), `supervisor.py:DaemonSupervisor` (child process, env merge, pdeathsig), `screens/` (home, now, logs, config, models, voices, picker), `config_schema.py:FIELDS` (extensibility seam mapping config keys→env vars), `discovery.py` (Ollama/Zen health + model options, wake/voice/registry), `logparse.py`/`logcolor.py`/`collapse.py`/`runlog.py`, `configfile.py`/`envfile.py`, `widgets.py` (`Stepper`, `NavBar`, `ScreenWidthRichLog`).

Look here for: daemon supervision, config editing via env overrides, log rendering, LLM tier badges, adding a config field.

## training/ + models/ (wake-word training)

Purpose: train and export wake-word ONNX models (isolated `.venv-train`, ROCm PyTorch).
- `train.py`/`train_batch.py` (entrypoints), `calcifer.yaml` (config), `manifest.py` (model registry CLI), `phrases.txt`, `bootstrap.sh`, `README.md`.
- `models/wake/calcifer.onnx` — the ~963 KB trained artifact loaded at runtime.

Look here for: wake model synthesis/augmentation/training, manifest management, FPPH gating.

## packaging/ + .github/ (distribution)

Purpose: single-file PyInstaller binaries + release automation.
- `assistant.spec`, `build.sh`, `entrypoint.py` (frozen `_MEIPASS` chdir, XDG state, CLI routing), `.github/workflows/release.yml` (x86_64 + aarch64 matrix on `v*` tags, smoke test).

Look here for: how the binary is built/bundled, release triggers, frozen-runtime paths.

## pluma/ (fledge planning specs)

Purpose: the project's own completed planning artifacts (all fledged).
- `plumage/PLM-001..003`, `feathers/FTHR-001..009` — self-update, AI-first search, persona revoice.

Look here for: feature history, acceptance-criteria themes, why a seam exists. See `domain.md`.

## root files & docs/

- Root: `pyproject.toml` (per-capability extras, ruff/pytest config), `config.yaml`/`default-config.yaml` (all tunables), `env.example`, `install.sh`, `start.sh`, `Makefile`, `README.md`, `AGENTS.md`, `CLAUDE.md`, `opencode.json`, `verify_calendar.py`/`verify_wikipedia.py` smoke scripts.
- `docs/` — `compass_artifact_*.md` (reference architecture) + `verification-loop-and-llm-tui-plan.md` (verify subsystem + TUI provider-awareness design).

Look here for: build/run commands, full config surface, external design rationale.
