# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
source .venv/bin/activate
pip install -e ".[dev]"          # core + pytest/pytest-asyncio/ruff
pytest                           # all tests
pytest tests/test_pipeline.py    # one file
pytest tests/test_router.py -k route_falls_back   # one test
ruff check assistant tests       # lint (line-length 100)
python -m assistant.app          # boot the daemon (Ctrl-C to stop)
```

Heavy/native deps are split into per-capability extras (`tts`, `wake`, `stt`,
`vad`, `llm`, `nlu`, `scheduling`, `search`, `gcal`) and installed only as
needed — see README for the Ollama/Piper prerequisites.
Tests run without the native extras: anything that touches a model or device is
stubbed, so `pip install -e ".[dev]"` alone is enough to run the suite.

## Architecture

Offline-first voice assistant. The flow is a single async loop in
`assistant/core/pipeline.py`:

> wake word → record (VAD) → transcribe (STT) → route → skill → speak (TTS)

**Interface-per-capability.** Each capability lives in its own package with an
ABC `base.py` and concrete implementation(s) beside it: `wake/`, `stt/`, `llm/`,
`tts/`, `nlu/`, `audio/`, `search/`, `weather/`, `calendar/`, plus `scheduling/`
(`ReminderScheduler`, `CalendarWatcher`) and `storage/` (SQLite `ReminderStore`,
`CalendarStateStore`); `sync/` and `connectivity/` remain stubs. `VoicePipeline`
depends only on the base classes; it never imports a
concrete provider. **When adding a capability or swapping an implementation, code
against the `base.py` ABC — do not let the pipeline reach for a concrete type.**

**`app.py` is the only wiring point.** It is the composition root: it reads
`Config`, constructs every concrete implementation (`PiperTTS`,
`LivekitWakeDetector`, `FasterWhisperSTT`, `OllamaProvider`,
skills…), and injects them into `VoicePipeline`. Construction-time choices
(which skills, the default skill) live here, not inside the
components.

**Remote is an optional accelerator, never a hard dependency.** Local
implementations are the guaranteed path; cloud/remote always sits behind an
interface with a local fallback (`connectivity/`, `sync/` are stubs reserving
that seam). Providers health-check at boot and degrade with a clear log warning
rather than crashing (see `OllamaProvider.health()` and the boot check in `app.py`).

**Skills are plug-ins.** A capability = one `Skill` subclass (`skills/base.py`)
declaring `name` + `intents`, registered via `SkillRegistry.register(...)`.
Routing never hard-codes skill names. Routing is the orchestrator's tool-calling
loop (`core/orchestrator.py`): each skill intent is exposed as a tool schema via
`SkillRegistry.tool_schemas()`, and the LLM either calls one tool (its arguments
populate `Intent.slots`) or answers directly. Any LLM/JSON failure or turn
timeout degrades to the `default=True` skill (`GeneralSkill`), which itself
handles the offline case with a spoken message.

**`core/events.py` holds the shared dataclasses** (`WakeEvent`, `Command`,
`Intent`, `SkillResult`) that flow down the pipeline. They live in `core/` so the
capability packages can pass them without importing each other — this is the rule
that keeps the dependency graph acyclic. Keep new cross-stage records here.

**`core/standdown.py` holds shared runtime state.** A single `StandDown`
("stop listening") instance is built in `app.py` and threaded into the
pipeline, reminder scheduler, calendar watcher, control channel, and
`StandDownSkill`. Consumers poll `.active` on their own tick — there is no
background timer task — so a timed stand-down simply expires, and a daemon
restart clears it.

**Config is the single source of truth** (`core/config.py`, pydantic-settings).
`config.yaml` → typed models; any value is overridable by `ASSISTANT_*` env vars
with `__` for nesting (e.g. `ASSISTANT_LLM__MODEL=llama3.2:3b`). Precedence:
explicit init args > env > `config.yaml`. Every device id, model path, and
threshold is config so the Raspberry Pi 5 deployment is config-only. **Add new
tunables as a typed field on the relevant `*Config` model, mirrored in both
`config.yaml` and `default-config.yaml` — never hard-code a path, threshold, or
device id in a component.**

**The monitor TUI is a separate top-level package** (`tui/`, a sibling of
`assistant/`, run with `python -m tui`). It supervises the daemon as a child
process (`python -m assistant.app` over a stdin control channel) and never
imports the pipeline/skills/LLM code or any native deps — its only `assistant`
imports are `core.config.Config` and `wake.registry`. **Keep this dependency
one-directional (`tui` → `assistant`); nothing under `assistant/` may import
`tui`.**

The TUI's deployment target is the Raspberry Pi 5's attached **320x480 px
display in portrait** — roughly a 40×30-cell terminal at a typical font size —
operated by **touch only** (keyboard input is a desktop-testing convenience,
never a requirement). Design every screen for that grid first: one focused
screen per job (see `tui/screens/`), full-width height-3 buttons, steppers and
pickers instead of text inputs, and no horizontal overflow at 40 columns
(`tests/test_tui_screens.py` enforces this).

## Conventions

- All pipeline-facing capability methods are `async`. `pytest` runs in
  `asyncio_mode = auto`, so `async def test_...` works without a marker.
- Components take primitive/config values in `__init__` (paths, thresholds), not
  the whole `Config` object — that keeps them unit-testable in isolation.
- The remaining stub packages (`sync/`, `connectivity/`) and base classes are
  deliberate seams for future capabilities, not dead code — don't delete them.
