---
generated: 2026-07-07T07:06:00Z
commit: 02f839d7a116780b02510c2d5b339c23c64a51f5
agent: fledge-forager
fledge_version: unknown
---

# Modules

Repository map, organized by directory. Each entry gives purpose, key files, and where to look for a given concern. `fledge scan` reports nine top-level modules (`assistant/`, `tui/`, `tests/`, `training/`, `models/`, `packaging/`, `docs/`, `pluma/`, `.github/`, plus `root`); `assistant/` and `tests/` are large enough that this map breaks them down by subpackage.

## root (repo top level)

Project configuration, install/start scripts, release pipeline, and smoke-test utilities.

- Key files: `config.yaml` + `default-config.yaml` (live config + documented template), `pyproject.toml` (metadata, per-capability optional extras, ruff line-length 100, `asyncio_mode = auto`), `install.sh` (venv + extras + models + Ollama + optional systemd), `start.sh` (activate venv, reap orphan daemon, launch TUI), `Makefile` (`release`, `clean`), `env.example`, `opencode.json` (OpenCode Zen metadata), `.python-version` (3.12.13), `verify_calendar.py` + `verify_wikipedia.py` (end-to-end smoke checks), `.github/workflows/release.yml` (x86_64 + aarch64 binaries on `v*` tags).
- Look here for: how to install/run/build, config precedence, optional extras, licensing (AGPL-3.0), CI/release.

## assistant/ — daemon package

### assistant (app root)
Composition root and first-run provisioning.
- Key files: `app.py` (`main()`, async `_run()`, factories `_build_llm`/`_build_one_llm`/`_build_search`, `_config_dump` secret masking), `bootstrap.py` (`doctor`/`bootstrap` subcommand: ensure Ollama + STT models), `__init__.py` (`__version__ = "0.1.0"`).
- Look here for: how every capability is constructed and injected; skill registration order; the default skill; **how search providers are assembled (`_build_search`)**.

### assistant/core
Orchestration heart: the pipeline, routing, config, events, shared state.
- Key files: `pipeline.py:VoicePipeline` (the async loop), `orchestrator.py:Orchestrator` (tool-calling routing), `config.py` (all `*Config` pydantic models incl. `WebSearchConfig`), `events.py` (shared dataclasses), `verify.py` (`Verdict`, `verify()`), `standdown.py:StandDown`, `arbiter.py:AudioArbiter`, `conversation.py`, `control.py:ControlChannel`, `speech.py:Speaker`, `persona.py`, `state.py:StateEmitter`, `logging.py:JsonlFormatter`.
- Look here for: routing logic, verification loop, config schema, the `@@STATE` feed, stand-down/arbiter semantics.

### assistant/audio
Audio I/O abstraction, VAD recording, AEC, earcons, mic fan-out.
- Key files: `base.py` (`AudioIn`/`AudioOut`), `sounddevice_io.py` (PortAudio), `devices.py` (`select_devices`), `aec.py` (`SpeexEchoCanceller`, `build_aec`), `mic_hub.py:MicHub` (tap for barge-in), `recorder.py:VadRecorder`, `processing.py:normalize_peak`, `earcon.py` (synthesized tones).
- Look here for: device selection, echo cancellation, VAD end-of-speech, barge-in tap.

### assistant/wake, stt, tts, llm, nlu (voice I/O + reasoning)
Each an ABC + concrete impl.
- Key files: `wake/{base,livekit_detector,registry}.py`, `stt/faster_whisper_stt.py`, `tts/piper_tts.py`, `llm/{base,ollama_provider,opencode_zen_provider,fallback_provider}.py`, `nlu/timespec.py` (hybrid regex+LLM reminder/timer parser).
- Look here for: wake phrase derivation, Whisper transcription, Piper synthesis, LLM `complete`/`chat`/`chat_tools`/`health`, provider fallback + retry, spoken-time parsing.

### assistant/search — web-search capability (focus area)
Pluggable web search behind `SearchProvider`.
- Key files: `base.py` (`SearchProvider` ABC, `SearchResult` dataclass, `domain()` util), `ddgs_provider.py:DdgsSearch` (DuckDuckGo via `ddgs`), `wikipedia.py:WikipediaSearch` (Wikipedia Action API via httpx), `multi.py:MultiSearch` (concurrent fan-out, round-robin merge, URL dedup), `__init__.py` (exports `WikipediaSearch`).
- Look here for: **the exact seam a new AI-first provider (Tavily/Exa/Brave) must implement**, provider composition/merge semantics, and result shape. Paired with `assistant/skills/web_search.py` (the agentic skill) and `WebSearchConfig` in `core/config.py`.

### assistant/skills
Plug-in intent handlers exposed to the orchestrator as tools.
- Key files: `base.py` (`Skill` ABC, `SkillRegistry`, `tools()`/`tool_schemas()`), `web_search.py:WebSearchSkill` (**agentic search loop**), `calendar.py`, `reminder.py`, `timer.py`, `weather.py`, `clock.py`, `stand_down.py`, `general.py` (default fallback, exports no tool).
- Look here for: how intents become tools, per-skill slots/handlers, and the web-search refine→search→assess→answer loop with prompt-injection defenses.

### assistant/calendar, weather, scheduling, storage (services)
- Key files: `calendar/{base,google_calendar,extraction,blocklist}.py`, `weather/{base,open_meteo}.py`, `scheduling/{scheduler,calendar_watcher}.py`, `storage/{reminders,calendar_state}.py` (SQLite).
- Look here for: Google Calendar REST, Open-Meteo forecast/geocode, reminder/timer persistence + schema migrations, proactive announce loops, calendar dedup + blocklist.

### assistant/connectivity, sync (stubs)
Deliberate seams for future remote acceleration — `ConnectivityService`, `ProviderRouter`, `SyncAdapter`/`NoopSyncAdapter`. Not dead code; do not delete.

## tui/ — monitor TUI
Textual app supervising the daemon; touch-first, 40×30 portrait.
- Key files: `app.py:AssistantTUI` (thick app: supervisor, health, logs, pulls, config), `supervisor.py:DaemonSupervisor`, `config_schema.py` (declarative `FIELDS`), `configfile.py`/`envfile.py`, `discovery.py` (Ollama/Zen/registry/voice providers), `logparse.py`/`logcolor.py`/`collapse.py`/`runlog.py`, `widgets.py` (`Stepper`, `NavBar`, `ScreenWidthRichLog`), `screens/{home,now,logs,config,models,voices,picker}.py`.
- Look here for: daemon supervision, live config editing (Save/Apply/Reset), model browsing/pulling from ollama.com, Piper voice downloads, the `@@STATE` UI, the 40-column overflow constraint.

## training/ (+ models/)
Wake-word model training in an isolated ROCm venv.
- Key files: `train.py` (single-model), `train_batch.py` (multi-phrase from `phrases.txt`), `manifest.py` (`models/wake/models.json` registry: upsert/list/regen/select), `calcifer.yaml` (production config), `bootstrap.sh` (ROCm PyTorch + livekit-wakeword), `README.md`. `models/wake/calcifer.onnx` (~963 KB) is the produced artifact consumed by `assistant/wake/livekit_detector.py`.
- Look here for: how the wake model is produced, FPPH gating, smoke runs, GPU/ROCm setup.

## packaging/
PyInstaller single-file build.
- Key files: `assistant.spec` (collects ONNX models + native libs), `build.sh` (fresh venv, `[all,tui]`, native-arch), `entrypoint.py` (frozen entry: `sys._MEIPASS`, XDG redirection, subcommand routing).
- Look here for: how the binary is bundled, what gets included, frozen-app path handling.

## pluma/ + docs/ (specs)
Fledge spec store and design docs.
- Key files: `pluma/plumage/PLM-001-…` (self-update/restart-in-place plumage), `pluma/feathers/FTHR-001-…` + `FTHR-002-…` (implementation slices), `docs/compass_artifact_…md` (reference architecture for a privacy-preserving local assistant), `docs/verification-loop-and-llm-tui-plan.md` (the verify-loop + provider-aware-TUI spec that shipped).
- Look here for: intended/authored capabilities, acceptance criteria, design rationale.

## tests/
Full suite; native deps stubbed. Broken down in `testing.md`. Groups: core (`test_pipeline`, `test_orchestrator*`, `test_config`, `test_verify`, …), capabilities (providers/skills incl. **search: `test_ddgs_provider`, `test_multi_search`, `test_wikipedia_provider`, `test_web_search_skill`**), TUI (`test_tui_*`, incl. the 40-col overflow gate), and eval (`tests/eval/` replay + live tool-call harness).

## .github/
`workflows/release.yml` — tag-triggered dual-arch binary build/release.
