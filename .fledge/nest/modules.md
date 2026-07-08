---
generated: 2026-07-08T00:34:07Z
commit: 0a67e65dc3d33b2e9c911f1296eef515124fa678
agent: fledge-forager
fledge_version: unknown
---

# Modules

Repo map organized by module. Two Python packages ship: `assistant/` (the daemon) and `tui/` (the monitor). Supporting top-level directories cover training, packaging, specs, and tests. Entries below list purpose, key files, and where to look for specific concerns.

## assistant/ (daemon package)

### assistant/ (root)
- **Purpose:** Daemon entry + composition root + first-run provisioning.
- **Key files:** `app.py` (`main()`, `_run()`, `_build_llm`/`_build_one_llm`/`_gateway_base_url`/`_llm_unhealthy_warning`, `_build_search`, `_config_dump`), `bootstrap.py` (`run(args)` = `assistant doctor`: ensures Ollama installed/serving, STT model cached), `__init__.py` (`__version__ = "0.1.0"`).
- **Look here for:** how everything is wired, how the LLM/search providers are constructed from config, boot-time health checks and degradation warnings, provisioning.

### assistant/core/
- **Purpose:** Orchestration, config, pipeline, shared records, runtime state.
- **Key files:** `config.py` (16 `*Config` pydantic models + `Config`), `pipeline.py` (`VoicePipeline`), `orchestrator.py` (`Orchestrator` tool-calling loop), `events.py` (`WakeEvent`/`Command`/`Intent`/`SkillResult`/`Turn`/`ToolCall`), `verify.py` (`Verdict`, pre/post gates), `persona.py` (`canned()`, `with_persona()`, suffix), `revoice.py` (`Revoicer`), `speech.py` (`Speaker`), `standdown.py` (`StandDown`), `arbiter.py` (`AudioArbiter`), `control.py` (`ControlChannel`), `conversation.py`, `state.py` (`StateEmitter`), `selfupdate.py` (`restart_in_place`), `logging.py`.
- **Look here for:** config schema & precedence, routing/tool-calling, verify loop, persona/revoice seams, TUI control protocol, `@@STATE` emitter, in-place restart.

### assistant/llm/
- **Purpose:** LLM completions behind one ABC; Ollama + generic OpenAI-compatible gateways + fallback wrapper.
- **Key files:** `base.py` (`LLMProvider` ABC, `ChatResponse`), `openai_compatible_provider.py` (`OpenAICompatibleProvider`, `LLMResponseError`, `GATEWAYS`), `ollama_provider.py` (`OllamaProvider`), `fallback_provider.py` (`FallbackLLMProvider`).
- **Look here for:** the gateway table (`opencode-zen`, `openrouter`), OpenAI wire shape (`/chat/completions`, tools, `response_format`), retry/backoff classification, health checks, primary→fallback logic. Note: `opencode_zen_provider.py` was removed by PLM-004.

### assistant/skills/
- **Purpose:** Plug-in capabilities; one `Skill` subclass per domain.
- **Key files:** `base.py` (`Skill` ABC, `SkillRegistry`, `local_now`), `general.py` (`GeneralSkill`, `default=True`), `calendar.py`, `clock.py`, `reminder.py`, `timer.py`, `stand_down.py`, `update.py`, `weather.py`, `web_search.py`.
- **Look here for:** how intents become tool schemas, `Intent.slots` population, confirm-then-act (`handle_reply`), the default/offline fallback, per-skill behavior.

### assistant/search/, weather/, calendar/, nlu/ (external-info capabilities)
- **Purpose:** Web search, weather, calendar, and time-parsing behind ABCs.
- **Key files:** `search/base.py` (`SearchProvider`, `SearchResult`), `search/{ddgs_provider,tavily,exa,wikipedia,multi}.py`; `weather/base.py` (`WeatherProvider`, `Place`, `Forecast`), `weather/open_meteo.py`; `calendar/base.py` (`CalendarProvider`, `CalendarEvent`, `speakable_title`), `calendar/{google_calendar,extraction,blocklist}.py`; `nlu/timespec.py` (`parse_duration`, `extract_reminder`, `parse_management`, `ReminderSpec`, `ManagementAction`).
- **Look here for:** the per-provider secret precedent (`tavily_api_key`/`exa_api_key` constructor params), multi-provider fan-out/merge, query-type routing (factual→Tavily, semantic→Exa), LLM-based intent extraction, reminder/duration parsing.

### assistant/audio/, stt/, tts/, wake/ (voice I/O)
- **Purpose:** Microphone/speaker I/O, echo cancellation, VAD recording, transcription, synthesis, wake detection.
- **Key files:** `audio/{base,sounddevice_io,devices,mic_hub,aec,recorder,processing,earcon}.py`; `stt/{base,faster_whisper_stt}.py`; `tts/{base,piper_tts}.py`; `wake/{base,livekit_detector,registry}.py`.
- **Look here for:** ABCs vs concrete providers, barge-in (tap/drain/AEC), VAD end-of-speech, earcons, wake model registry & phrase derivation from `models/wake/models.json`.

### assistant/scheduling/, storage/ (proactive + persistence)
- **Purpose:** Reminder/timer firing, calendar watching, and SQLite state.
- **Key files:** `scheduling/scheduler.py` (`ReminderScheduler`), `scheduling/calendar_watcher.py` (`CalendarWatcher`), `storage/reminders.py` (`ReminderStore`, `Reminder`), `storage/calendar_state.py` (`CalendarStateStore`).
- **Look here for:** poll loops, catch-up on boot, arbiter serialization, dedup by `(event_id, start_at)`, table schemas & migration.

### assistant/sync/, connectivity/ (stub seams)
- **Purpose:** Reserved future seams — do not delete.
- **Key files:** `sync/base.py` (`SyncAdapter`, `NoopSyncAdapter`), `connectivity/base.py` (`ConnectivityService`, `ProviderRouter`).
- **Look here for:** the intended contract for future cloud sync and connectivity routing.

## tui/ (monitor package)
- **Purpose:** Touch TUI supervising the daemon on the Pi 5 320×480 portrait display; config/env editing, live logs, model/voice management.
- **Key files:** `app.py` (`AssistantTUI`), `supervisor.py` (`DaemonSupervisor`, `free_ollama_port`), `config_schema.py` (`FIELDS`, `Field`), `configfile.py` (`write_fields`), `envfile.py` (`.env` parse), `discovery.py` (Ollama/Zen/registry/Piper clients), `logparse.py`/`logcolor.py`/`collapse.py`/`runlog.py`, `widgets.py`, `screens/{home,config,logs,models,now,picker,voices}.py`.
- **Look here for:** daemon supervision & control channel, `.env`/config.yaml editing surface, the 40-column layout constraint, `@@STATE` parsing, model/voice download flows. Imports only `assistant.core.config` and `assistant.wake.registry`.

## training/
- **Purpose:** Train the Calcifer wake-word model (`models/wake/calcifer.onnx`) with livekit-wakeword + Piper synthesis + augmentation.
- **Key files:** `train.py`, `train_batch.py`, `manifest.py` (`models/wake/models.json`), `calcifer.yaml`, `phrases.txt`, `bootstrap.sh`, `README.md`.
- **Look here for:** wake training pipeline, ROCm/GPU setup, manifest/registry management, isolated `.venv-train`.

## packaging/ (+ .github/, models/)
- **Purpose:** PyInstaller single-file frozen binaries; GitHub Actions release; trained models.
- **Key files:** `packaging/assistant.spec`, `packaging/build.sh`, `packaging/entrypoint.py`, `.github/workflows/release.yml`, `models/wake/calcifer.onnx` (~963 KB binary), `models/wake/models.json`, `models/piper/*` voices.
- **Look here for:** how the daemon/TUI freeze into `dist/assistant-<arch>`, `_MEIPASS`/XDG writable-path handling, per-arch CI builds triggered by `v*` tags.

## pluma/ (fledge spec store)
- **Purpose:** Feature specifications — plumages (feature areas) and feathers (implementable slices). No production code.
- **Key files:** `plumage/PLM-001..004-*.md`, `feathers/FTHR-001..012-*.md`. PLM-004 + FTHR-010/011/012 cover the OpenAI-compatible LLM gateway / OpenRouter work; all 4 plumages and 12 feathers are `status: fledged`.
- **Look here for:** feature intent, functional/acceptance criteria, dependency DAG, why the current LLM gateway design exists.

## tests/
- **Purpose:** pytest suite; runs without native extras (`.[dev]` is enough); all model/device/network access stubbed.
- **Key files:** `test_config.py`, `test_llm_dispatch.py`, `test_app_llm_diagnostics.py`, `test_openai_compatible_provider.py`(+`_guards`), `test_openrouter_compat.py`, `test_fallback_provider.py`, `test_ollama_provider.py`, `test_orchestrator.py`(+`_verify`), `test_pipeline.py`, `test_speech_invariants.py`, `test_revoice.py`, skill/capability tests (`test_*_skill.py`, `test_*_provider.py`), `test_tui_*.py` (incl. `test_tui_screens.py` 40×30 gate), and `tests/eval/` (live + replay orchestrator eval).
- **Look here for:** how each subsystem is tested, fake/stub patterns, the config/LLM test coverage, the eval harness. See `testing.md`.

## root (repo top-level files)
- **Purpose:** Config, packaging metadata, install/run scripts, docs, smoke tests.
- **Key files:** `config.yaml`, `default-config.yaml`, `.env.example`, `pyproject.toml`, `install.sh`, `start.sh`, `Makefile`, `README.md`, `CLAUDE.md`, `AGENTS.md`, `opencode.json`, `verify_calendar.py`, `verify_wikipedia.py`, `.python-version`, `LICENSE` (AGPL-3.0).
- **Look here for:** the effective LLM/search config, secrets template, per-capability extras, how to install/run, ruff/pytest settings.
