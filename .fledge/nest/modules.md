---
generated: 2026-07-07T02:45:41Z
commit: 8d180f04862c48fdddc61804b81dafcd0f620344
agent: fledge-forager
fledge_version: unknown
---

# Modules

A map of the repository by directory. Each entry gives the module's purpose, its key files, and where to look for specific concerns. Two top-level Python packages (`assistant/`, `tui/`) plus supporting directories.

## assistant/core — pipeline, orchestration, shared state

The heart of the daemon: the async pipeline loop and everything cross-cutting.
Key files: `pipeline.py` (`VoicePipeline` — the wake→record→transcribe→route→speak loop, conversation/follow-up, barge-in, continuation decision), `orchestrator.py` (`Orchestrator` — LLM tool-calling loop with JSON + general-skill fallback), `events.py` (shared dataclasses `WakeEvent`, `Turn`, `Command`, `ToolCall`, `Intent`, `SkillResult`), `standdown.py` (`StandDown` polled shared pause state), `control.py` (`ControlChannel` — stdin verbs from TUI), `config.py` (`Config` + ~20 nested pydantic models), `persona.py` (Calcifer voice suffix), `arbiter.py` (`AudioArbiter` audio lock), `state.py` (`StateEmitter` `@@STATE` feed), `conversation.py`, `speech.py`, `logging.py`.
Look here for: the confirm/reply seam (`SkillResult.expects_reply`, `pipeline._handle_reply`), the tool-calling loop, control-verb dispatch, persona/sign-off wording, and where a self-update restart hook would live.

## assistant/skills — the skill plug-in system

One `Skill` subclass per capability; the plug-in contract.
Key files: `base.py` (`Skill` ABC + `SkillRegistry` — register/get/tool_schemas), `general.py` (`GeneralSkill`, the `default=True` fallback), `stand_down.py` (`StandDownSkill` — quirky sign-off lines), `reminder.py` (`ReminderSkill` — confirm-then-act bulk delete via `expects_reply`), `timer.py`, `clock.py`, `weather.py`, `web_search.py` (agentic multi-round search with injection defense), `calendar.py`.
Look here for: how to add a new skill/intent, the tool-schema shape, the confirm-then-act pattern, and the sign-off/persona wording a self-update skill would emulate.

## assistant/llm, stt, tts, wake, nlu — capability providers

ABC + concrete implementation per capability.
Key files: `llm/base.py` + `llm/ollama_provider.py` (`OllamaProvider` — chat/complete/chat_tools/health over httpx), `stt/faster_whisper_stt.py`, `tts/piper_tts.py`, `wake/livekit_detector.py` + `wake/registry.py` (phrase-from-filename derivation, `models/wake/models.json` manifest), `nlu/timespec.py` (regex+LLM time extraction; `router.py`/`command_router.py`/`keyphrase_router.py` were deleted — routing now flows through the orchestrator).
Look here for: provider interfaces, boot health-check patterns, wake phrase resolution.

## assistant/audio — audio I/O

Mic capture, VAD, playback, echo cancellation, earcons.
Key files: `base.py` (`AudioIn`/`AudioOut` ABCs), `sounddevice_io.py`, `recorder.py` (`VadRecorder`), `mic_hub.py` (`MicHub` fan-out + barge-in tap), `aec.py` (`SpeexEchoCanceller`, degrades to `None`), `earcon.py` (synthesized tones/chimes), `devices.py`, `processing.py`.
Look here for: barge-in tap wiring, earcon cues, device selection, preroll.

## assistant/calendar, scheduling, search, weather, storage, connectivity, sync — data/capabilities

Key files: `calendar/google_calendar.py` + `calendar/blocklist.py` + `calendar/extraction.py`, `scheduling/scheduler.py` (`ReminderScheduler` poll loop) + `scheduling/calendar_watcher.py` (`CalendarWatcher`), `search/multi.py` + `ddgs_provider.py` + `wikipedia.py`, `weather/open_meteo.py`, `storage/reminders.py` (`ReminderStore` SQLite) + `storage/calendar_state.py` (`CalendarStateStore`), `connectivity/base.py` + `sync/base.py` (stubs).
Look here for: SQLite schemas, poll-loop + standdown/arbiter integration, Google Calendar auth, multi-provider search.

## assistant/app.py, bootstrap.py — composition root & provisioning

Key files: `app.py` (`main()`/`_run()` — the only wiring point), `bootstrap.py` (`doctor` subcommand — ensures Ollama/STT models ready).
Look here for: how everything is constructed and injected, boot health checks, graceful-degrade wiring, and the shutdown path (currently just KeyboardInterrupt).

## tui — the monitor UI

Textual app supervising the daemon on a 320×480 portrait touch display (~40×30 cells).
Key files: `supervisor.py` (`DaemonSupervisor` — spawn/restart/stop the daemon child, stdin/stdout channel, `prctl(PR_SET_PDEATHSIG)`, `free_ollama_port()`), `app.py` (`AssistantTUI` controller), `screens/` (home, now, logs, config, models, voices, picker), `config_schema.py` (declarative `FIELDS` → `ASSISTANT_*` env vars), `discovery.py` (Ollama/registry/voice discovery), `logparse.py`/`logcolor.py`/`collapse.py`, `widgets.py` (`Stepper`, `NavBar`, `ScreenWidthRichLog`).
Look here for: daemon supervision/restart lifecycle, the control-channel wire format, how config edits become env overrides, and how the daemon would appear to the supervisor during a re-exec.

## tests — unit + integration suite

74 files, pytest with `asyncio_mode = auto`.
Key files: `test_pipeline.py` (1466 lines — pipeline state machine, conversation, barge-in, standdown), `test_orchestrator.py` (tool-calling/fallback), `test_control.py`, `test_persona.py`, `test_standdown.py`, skill tests (`test_*_skill.py`), `test_tui_supervisor.py`, `test_tui_screens.py` (enforces 40-col fit), `tests/eval/` (tool-calling + replay harness).
Look here for: how to test a new pipeline seam or skill; existing fakes (`ScriptedLLM`, `FakeDetector`, `FakeSupervisor`, `ReplayProvider`). See `testing.md`.

## training — wake-word training pipeline

Peripheral to the runtime; trains the Calcifer ONNX wake model via `livekit-wakeword` on ROCm.
Key files: `train.py`, `train_batch.py`, `manifest.py` (`models/wake/models.json` registry), `calcifer.yaml`, `bootstrap.sh`, `phrases.txt`.
Look here for: how the wake model is produced and registered; not touched by app runtime changes.

## packaging, .github — freeze & release

Key files: `packaging/entrypoint.py` (frozen entry: env/chdir setup, CLI subcommand routing — **critical for re-exec target**), `packaging/assistant.spec` (PyInstaller), `packaging/build.sh`, `.github/workflows/release.yml` (native x86_64 + aarch64 builds).
Look here for: whether the app runs frozen vs. `python -m`, and what `os.execv` must target after a self-update.

## specs, docs — design specs & research

Key files: `specs/mute-for-duration.md` (the StandDown spec — the house style a self-update spec should follow), `specs/speaker-gate.md`, `specs/web-search-answers.md`, `docs/compass_artifact_*.md` (research artifact on self-hosted assistant architecture).
Look here for: the spec template/conventions and the StandDown design that self-update most resembles.

## root — project files

`pyproject.toml` (extras per capability), `config.yaml` + `default-config.yaml` (config surface), `install.sh`, `start.sh` (venv + daemon reap + launch TUI), `Makefile`, `README.md`, `AGENTS.md`, `CLAUDE.md`, `models/wake/calcifer.onnx` (binary), `verify_calendar.py`/`verify_wikipedia.py` (smoke scripts).
Look here for: how to build/install/run, the full config surface, and env-override precedence.
