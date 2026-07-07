---
generated: 2026-07-07T02:45:41Z
commit: 8d180f04862c48fdddc61804b81dafcd0f620344
agent: fledge-forager
fledge_version: unknown
---

# Conventions

Coding, architectural, and process conventions observed consistently across the codebase. Follow these when extending the daemon or adding a feature (e.g., a self-update skill); reviewers enforce them.

## Architectural rules

- **Interface-per-capability.** Every capability is a package with an ABC in `base.py` and concrete implementation(s) beside it. The pipeline depends only on the ABC, never a concrete provider (`assistant/core/pipeline.py`, `CLAUDE.md`). Adding or swapping an implementation means coding against `base.py`.
- **`app.py` is the only wiring point.** All concrete construction, skill registration, and default-skill choice happen in `assistant/app.py:_run()`. Do not instantiate providers or hard-code choices inside components.
- **Shared cross-stage records live in `core/events.py`.** New records that flow between pipeline stages go here so capability packages don't import each other and the dependency graph stays acyclic.
- **`tui` → `assistant` is one-directional and narrow.** The TUI imports only `assistant.core.config.Config` and `assistant.wake.registry`. Nothing under `assistant/` imports `tui` (`CLAUDE.md`, `tui/app.py`).
- **Stub seams are not dead code.** `sync/` and `connectivity/` base classes are deliberate future seams; don't delete them (`CLAUDE.md`).
- **Remote is an optional accelerator.** Local implementations are the guaranteed path; cloud/remote always sits behind an interface with a local fallback and boot health-check that degrades with a logged warning, never a crash (`OllamaProvider.health()`, `assistant/app.py`).

## Config

- **Config is the single source of truth** (`assistant/core/config.py`, pydantic-settings). Every device id, model path, and threshold is a typed field on a `*Config` model. No magic numbers or hard-coded paths in component code.
- **New tunables must be added in three places**: a typed field on the relevant `*Config` model, plus mirrored in both `config.yaml` and `default-config.yaml` (`default-config.yaml` documents every key with defaults + comments).
- **Env override format**: `ASSISTANT_<SECTION>__<FIELD>` with `__` for nesting (e.g. `ASSISTANT_LLM__MODEL=llama3.2:3b`). Precedence: explicit init args > env > `config.yaml` > pydantic defaults (`tests/test_config.py`).

## Component construction

- **Components take primitives in `__init__`, never the whole `Config`** (paths, thresholds, IDs, provider instances) — keeps them unit-testable in isolation. The whole-`Config` read happens only in `app.py`.
- **Dependency injection everywhere**, including injectable clocks (`now=` callables) and token sources for deterministic tests.

## Async & concurrency

- **All pipeline-facing capability methods are `async`.** Blocking native work (Whisper, Piper) is wrapped in `asyncio.to_thread()` to keep the event loop free (`assistant/stt/faster_whisper_stt.py`, `assistant/tts/piper_tts.py`).
- **No background timer tasks for timed state.** Consumers of `StandDown` and the poll loops poll `.active`/`due()` on their own tick (`assistant/core/standdown.py`, `assistant/scheduling/scheduler.py`).
- **Audio is serialized through `AudioArbiter`.** Proactive pollers (reminders, calendar) hold the arbiter before speaking so they never collide with capture/playback (`assistant/scheduling/scheduler.py`, `assistant/core/arbiter.py`).
- **UTC epoch seconds everywhere** in storage and poll loops (`time.time()`); only skills convert wall-clock to epoch (`assistant/storage/reminders.py`).

## Error handling & degradation

- **Graceful degradation is pervasive.** Every external call (LLM, provider, store, playback) is wrapped in try/except with a spoken apology or logged warning; failures never propagate to crash the pipeline. LLM/tool/JSON failures degrade to the `default=True` `GeneralSkill` (`assistant/core/orchestrator.py`, `assistant/skills/*`).
- **Health checks return bool, never throw** (`OllamaProvider.health()`).

## Skill & routing patterns

- **Routing never hard-codes skill names.** Intents are exposed as tool schemas via `SkillRegistry.tool_schemas()`; the intent name *is* the tool name (`assistant/skills/base.py`).
- **Confirm-then-act via `expects_reply`.** A destructive/confirmable action returns `SkillResult(expects_reply=True)`; the pipeline holds that skill and routes the user's next utterance to `skill.handle_reply(Command)` without re-orchestrating (one round only). See `ReminderSkill` bulk delete (`assistant/skills/reminder.py`, `pipeline.py`). **This is the seam a self-update confirmation would use.**
- **Text-slot fallback**: intent slots commonly back off to `intent.slots.get("text") or cmd.text` so both structured tool calls and text-only fallbacks route.
- **Persona injection is scoped.** Persona voice (`with_persona()`, `assistant/core/persona.py`) is appended only to final-reply prompts, never to tool-decision or JSON-structured prompts, so tool selection stays unaffected (`tests/test_persona.py`).
- **LLM calls carry `label="<action>"`** for JSONL trace/eval extraction; structured extraction requests use `json=True`.
- **Humanized speech**: durations/dates/times go through `assistant/nlu/timespec.py` helpers; no raw timestamps spoken.

## TUI conventions

- **Portrait-first, touch-only.** Design for 40×30 cells: full-width height-3 buttons, steppers/pickers instead of text inputs, no horizontal overflow at 40 columns (enforced by `tests/test_tui_screens.py`). No free-text config fields — all fields are select/multiselect/number/toggle (`tui/config_schema.py`).
- **Config edits become `ASSISTANT_*` env overrides** applied at daemon (re)start; "Save" persists to `config.yaml`, "Apply" restarts with env overrides.

## Style & tooling

- **Ruff, line length 100.** `ruff check assistant tests`.
- **Python 3.12** (pinned via `.python-version`).
- **Spec conventions** (`specs/`): a spec has a status line, author+date, context, behavior (spoken vs. typed paths), design (naming files/classes), "files to change", acceptance criteria (as numbered test cases), out-of-scope, and verification sections. `Command.spoken` distinguishes spoken (needs confirmation) vs. typed (trusted) input.

## Testing conventions

- **pytest with `asyncio_mode = auto`** — `async def test_...` needs no marker.
- **Tests run without native extras**; anything touching a model/device/network is stubbed. `pip install -e ".[dev]"` is sufficient.
- **Fakes mirror the ABC exactly** and record calls for assertion. See `testing.md`.
