---
generated: 2026-07-07T22:56:23Z
commit: 58fb2ba9bbeefc5db7d530261bcb3450573048fa
agent: fledge-forager
fledge_version: unknown
---

# Entry Points & Public Interfaces

How to run, build, and provision the project, and the public interfaces where execution enters each subsystem.

## Running the project

```bash
source .venv/bin/activate
pip install -e ".[dev]"          # core + pytest/pytest-asyncio/ruff (no native extras needed for tests)
python -m assistant.app          # boot the daemon (Ctrl-C to stop)
python -m tui                    # launch the monitor TUI (supervises the daemon)
./start.sh                       # TUI launcher: activate venv, reap orphan daemon, exec python -m tui
```

Console script (from `pyproject.toml`): `assistant` → `assistant.app:main`.

## Testing & linting

```bash
pytest                                            # all tests
pytest tests/test_pipeline.py                     # one file
pytest tests/test_router.py -k route_falls_back   # one test
ruff check assistant tests                        # lint, line-length 100
ASSISTANT_EVAL=1 pytest tests/eval/test_tool_eval.py   # opt-in live LLM tool-call eval
```

## Provisioning & smoke tests

- `assistant doctor` / `assistant bootstrap` → `bootstrap.py:run(args)` — ensures Ollama, LLM model, and STT cache are present.
- `./install.sh [--no-native|--no-venv|--no-pip|--no-wake|--no-piper-voice|--no-ollama] [--systemd]` — full host setup.
- `python verify_calendar.py` — Google Calendar end-to-end smoke (health, list, create→patch→delete).
- `python verify_wikipedia.py` — Wikipedia search smoke.

## Build & release

- `make release` → `bash packaging/build.sh` → PyInstaller onefile `dist/assistant-$(uname -m)` (`PYTHON_BIN=python3.12` override supported).
- Frozen binary CLI (`packaging/entrypoint.py`): `assistant --version|-V`, `assistant doctor|bootstrap`, `assistant tui`, bare `assistant` runs the daemon.
- `.github/workflows/release.yml` — on `v*` tag: builds x86_64 + aarch64, smoke-tests (`--version`, DEBUG daemon start | head -40), uploads artifacts, creates the GitHub Release.

## Daemon composition & lifecycle (`assistant/app.py`)

- `main()` — CLI entry; loads `Config()`, `select_devices()`, then `asyncio.run(_run(config, devices))`.
- `_run(config, devices)` — the composition root: constructs every concrete provider, wires shared `StandDown`, runs boot health checks (LLM, calendar), and launches pipeline + `ReminderScheduler` + `CalendarWatcher` + `ControlChannel` via `asyncio.gather()`.
- `_build_llm` / `_build_one_llm` — LLM provider dispatch: `provider == "opencode-zen"` → `OpenCodeZenProvider`, else `OllamaProvider`; wrapped in `FallbackLLMProvider` when `LlmConfig.fallback` is set and differs. **This is where a new LLM provider is registered.**

## Pipeline & routing interfaces (`core/`)

- `VoicePipeline.run()` — the main async loop. `.request_listen()` (tap-to-listen, skip wake), `.cancel()` (barge-in/stop), `.submit_text()` (TUI-typed command).
- `Orchestrator.handle(text, history, *, spoken, on_say) -> (SkillResult, Skill)` — routing entry; internally `_decide()` makes the tool decision (the exact call the eval harnesses exercise). `_messages(utterance, history)` builds the chat message list.
- `ControlChannel.run()` / `.dispatch(line)` — stdin verbs: `TEXT`, `SET key value`, `SAY [rate|]text`, `LISTEN`, `CANCEL`, `STOP`, `RESUME`.

## Capability ABCs (implement these to add/swap a provider)

- **LLM** (`llm/base.py:LLMProvider`) — `async complete/chat/chat_tools/health/aclose`; returns `str` or `ChatResponse`.
- **STT** (`stt/base.py:SpeechToText`) — `async transcribe(audio: bytes) -> str`.
- **TTS** (`tts/base.py:TextToSpeech`) — `async synthesize(text, length_scale=None) -> bytes`.
- **Wake** (`wake/base.py:WakeDetector`) — `process(frame) -> WakeEvent | None`, `reset()`. Phrase lookup: `wake.registry.phrases_for(refs)`.
- **Search** (`search/base.py:SearchProvider`) — `async search(query, *, count) -> list[SearchResult]`, `health`, `aclose`.
- **Weather** (`weather/base.py:WeatherProvider`) — `async geocode`, `forecast`, `health`, `aclose`.
- **Calendar** (`calendar/base.py:CalendarProvider`) — `async list_events/create_event/update_event/delete_event/health/aclose`.
- **Audio** (`audio/base.py`) — `AudioIn.stream()/.drain()/.set_tap()/.clear_tap()`; `AudioOut.play()/.stop()`.

## Skill interface (`skills/base.py`)

- `Skill.handle(cmd: Command, intent: Intent) -> SkillResult` (abstract); `Skill.handle_reply(cmd) -> SkillResult` (two-phase follow-ups); `Skill.tools() -> list[dict]` (tool schemas from declared intents).
- `SkillRegistry.register(skill, *, default=False)`, `.get(intent_type)`, `.intents`, `.tool_schemas()` — the orchestrator calls `tool_schemas()` to expose skills to the LLM; a tool call routes back to the matching skill's `handle()`. Register skills (and the single `default=True` `GeneralSkill`) in `app.py`.

## Scheduling & storage entry points

- `ReminderScheduler.run()`, `CalendarWatcher.run()` — async poll tasks launched from `app.py`.
- `ReminderStore` — `add/due/pending/delete/delete_pending/update_due/update_speech/close`.
- `CalendarStateStore` — `was_announced/mark/purge_before/add_blocked/remove_blocked/blocked_patterns/close`.

## Self-update (PLM-001)

`skills/update.py:UpdateSkill.handle()` → confirm (`expects_reply=True`); `handle_reply()` on affirmative sets `SkillResult.restart=True`; the pipeline honors it after `_speak()` and calls `core/selfupdate.py:restart_in_place()` (`os.execv(python, ["-m", "assistant.app"])`).

## TUI entry points (`tui/`)

- `python -m tui` → `__main__.py` → `app.main()` → `AssistantTUI().run()`; installs six screens (home, now, logs, config, models, voices) at mount.
- `DaemonSupervisor.start(overrides)` / `.stop()` / `.restart()` / `.send(line)` / `.lines()` — child-process control over the stdin channel + stdout stream. Config edits apply as `ASSISTANT_*` env on restart, or persist via `configfile.write_fields(path, values)`.

## Wake-word training (`training/`, isolated venv)

- `bash training/bootstrap.sh` — build `.venv-train` (ROCm PyTorch).
- `training/.venv-train/bin/python training/train.py [--smoke ...]` / `train_batch.py [phrases...]` — train/export ONNX to `models/wake/`.
- `python training/manifest.py {upsert|list|regen|select}` — manage the model manifest and write `wake.model_paths` to `config.yaml`.
