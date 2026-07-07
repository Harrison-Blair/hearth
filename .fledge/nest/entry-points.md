---
generated: 2026-07-07T07:06:00Z
commit: 02f839d7a116780b02510c2d5b339c23c64a51f5
agent: fledge-forager
fledge_version: unknown
---

# Entry Points & Public Interfaces

How to run and build the project, and the public interfaces execution flows through.

## Running the project

### Daemon
- `python -m assistant.app` → `assistant/app.py:main()` — boots the voice pipeline. Reads `Config`, selects audio devices, logs a boot diagnostic, then `asyncio.run(_run())`. `_run()` constructs every subsystem, starts them concurrently (`asyncio.gather`), and cleans up in a `finally` block. Also exposed as the `assistant` console script (`pyproject.toml [project.scripts]`).
- `assistant doctor` / `python -m assistant.bootstrap` → `assistant/bootstrap.py:run()` — idempotent provisioning: ensure Ollama daemon + model present, pre-warm the STT model. Returns 0/1.

### Monitor TUI
- `python -m tui` → `tui/__main__.py:main()` → `tui/app.py:AssistantTUI().run()` — supervises the daemon as a child and provides touch config/logs/models/voices. Launched conveniently by `./start.sh` (activates venv, reaps orphan daemon).

### Dev commands (`CLAUDE.md`)
```bash
source .venv/bin/activate
pip install -e ".[dev]"                              # core + pytest/pytest-asyncio/ruff
pytest                                               # all tests
pytest tests/test_pipeline.py                        # one file
pytest tests/test_router.py -k route_falls_back      # one test
ruff check assistant tests                           # lint
python -m assistant.app                              # boot the daemon
```

### Install / build / release
- `./install.sh [--minimal|--no-*|--systemd|--systemd-no-enable]` — platform detect, venv, pip extras, wake models, Piper voice, Ollama, optional systemd unit.
- `make release` → `packaging/build.sh` → `dist/assistant-$(uname -m)` (PyInstaller single-file, native-arch only). Frozen entry: `packaging/entrypoint.py:main()` routes `--version` / `doctor`|`bootstrap` / `tui` / (default) daemon, chdir's to `sys._MEIPASS`, redirects writable state to `$XDG_DATA_HOME/assistant/`.
- CI: `.github/workflows/release.yml` builds x86_64 + aarch64 on `v*` tags, smoke-tests the frozen import, attaches both binaries to the release.
- Smoke utilities: `python verify_calendar.py`, `python verify_wikipedia.py`.

## Core internal interfaces

### VoicePipeline (`assistant/core/pipeline.py`)
- `async run()` — the main loop (wake→record→transcribe→route→skill→speak; follow-ups, barge-in, continuation decisions).
- `request_listen()` — tap-to-listen (start a turn with no wake word).
- `cancel()` — abandon capture + stop playback.
- `async submit_text(text)` — inject a typed command (from the control channel).

### Orchestrator (`assistant/core/orchestrator.py`)
- `async handle(text, history, *, spoken, on_say) -> (SkillResult | None, Skill | None)` — route one utterance via the tool-calling loop with optional verify gates. Native→JSON→general fallback; degrades to `GeneralSkill`.
- `_decide(messages) -> ChatResponse` — the raw routing decision (used directly by the eval harness).

### SkillRegistry / Skill (`assistant/skills/base.py`)
- `SkillRegistry.register(skill, *, default=False)`, `.get(intent_type) -> Skill | None`, `.tool_schemas() -> list[dict]`, `.intents` property.
- `Skill`: `name`, `intents`, `tool_specs`; `async handle(cmd, intent) -> SkillResult`; `async handle_reply(cmd)` (for `expects_reply`); `tools()` (override to `[]` to answer directly).

### LLMProvider (`assistant/llm/base.py`)
`async complete(prompt, *, system, json, label)`, `async chat(messages, *, system, label)`, `async chat_tools(messages, *, system, tools, label) -> ChatResponse`, `async health() -> bool`, `aclose()`.

### Control channel (`assistant/core/control.py:ControlChannel`)
`async run()` reads stdin in a background thread; `async dispatch(line)` executes one verb. Verbs: `TEXT <utterance>`, `SET <key> <value>`, `SAY [rate|]<text>`, `LISTEN`, `CANCEL`, `STOP`, `RESUME`. This is the daemon side of the TUI supervisor pipe.

### StandDown / AudioArbiter
- `StandDown.engage(seconds)`, `.resume()`, `.active`, `.remaining` (`core/standdown.py`) — polled cooperative "stop listening" flag.
- `AudioArbiter` — single `asyncio.Lock`; `hold()`-style acquisition serializes capture, playback, and announcements (`core/arbiter.py`).

## Web-search capability interfaces (focus area)

### SearchProvider ABC (`assistant/search/base.py`) — the plug-in seam
- `async search(query: str, *, count: int) -> list[SearchResult]`
- `async health() -> bool`
- `async aclose() -> None`
Concrete: `DdgsSearch`, `WikipediaSearch`. Composite: `MultiSearch(providers, *, max_results)` implements the same `search`/`health`/`aclose` and fans out + merges.

### WebSearchSkill (`assistant/skills/web_search.py`)
- Name `web_search`, single intent `web_search` with required `query` slot (tool description gates it to real-time info, not general knowledge or weather).
- Entry: `handle()` → `_handle()` agentic loop: `_refine()` → `search()` → `_assess()` → answer/retry (≤ `max_rounds`); `_plain_summary()` fallback; `_say_soon()`/`_flush_speech()` for spoken progress; `_neutralize()`/`_result_blocks()` for injection-safe formatting.

### Wiring (`assistant/app.py:_build_search`, ~lines 60–93)
Reads `WebSearchConfig`, builds the provider list from `providers`, constructs `MultiSearch`, and injects it + `max_rounds` + `Speaker` into `WebSearchSkill`, which is registered in the `SkillRegistry`. **This is the function a new AI-first provider must be added to.**

## Capability provider interfaces
- Wake: `WakeDetector.process(frame) -> WakeEvent | None`, `reset()`; registry `phrase_for(ref)` / `phrases_for(refs)`.
- STT: `SpeechToText.transcribe(audio) -> str`.
- TTS: `TextToSpeech.synthesize(text, length_scale=None) -> bytes`; `.sample_rate`.
- Calendar: `CalendarProvider.list_events/create_event/update_event/delete_event/health/aclose` (`calendar/base.py`).
- Weather: `WeatherProvider.geocode(place) -> Place | None`, `forecast(lat, lon, *, name) -> Forecast`, `health`, `aclose`.
- Scheduling: `ReminderScheduler.run()`, `CalendarWatcher.run()` — async poll loops.
- Storage: `ReminderStore.add/due/pending/delete/delete_pending/update_due/update_speech`; `CalendarStateStore.was_announced/mark/purge_before/add_blocked/remove_blocked/blocked_patterns`.

## TUI supervisor interface (`tui/supervisor.py:DaemonSupervisor`)
`start(overrides)`, `stop()`, `restart(overrides)`, `send(line)`, `lines()` async iterator, `running`/`returncode` properties. Spawns `python -m assistant.app`, merges `os.environ` + `.env` + session overrides, streams stdout, writes control verbs to stdin.

## Eval harness entry points (`tests/eval/`)
- `python -m tests.eval.extract <log> -o <capture>` — filter daemon JSONL to `turn`/`llm.*` records.
- `python -m tests.eval.run_eval` — live tool-call eval against Ollama (exit 0 if ≥0.90).
- `python -m tests.eval.run_replay` — offline replay against captures (exit 0 if ==1.0).
