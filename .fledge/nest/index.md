---
generated: 2026-07-07T02:45:41Z
commit: 8d180f04862c48fdddc61804b81dafcd0f620344
agent: fledge-forager
fledge_version: unknown
---

# Context Index

Context for Calcifer, an offline-first voice assistant daemon (`assistant/`) plus a separate Textual monitor TUI (`tui/`). Generated for planning a "self-update" capability (spoken confirmation → quirky sign-off → `os.execv` restart-in-place, no network fetch). Load docs per the `Read this when:` routing lines below.

## architecture.md
How the daemon is wired end to end: the async pipeline loop, interface-per-capability, the `app.py` composition root, shared `StandDown`/`AudioArbiter` state, orchestration, and the TUI daemon-supervision lifecycle. Includes a dedicated analysis of the self-update seams (confirm-then-act reply, persona sign-off, re-exec target, and how `os.execv`'s same-PID/preserved-fd behavior interacts with the supervisor).
Read this when: you need the big picture of how components relate, or you are placing a new cross-cutting seam like a restart hook.

## modules.md
Directory-by-directory map (assistant/core, skills, capability packages, tui, tests, training, packaging, specs, root) with each module's purpose, key files, and a "Look here for" pointer.
Read this when: you need to find which files own a concern before diving in.

## conventions.md
The enforced rules: interface-per-capability, `app.py`-only wiring, config-as-single-source-of-truth (three-place rule + `ASSISTANT_*` overrides), async/arbiter/standdown patterns, graceful degradation, the `expects_reply` confirm-then-act pattern, scoped persona injection, TUI portrait/touch rules, and testing/spec conventions.
Read this when: you are writing code or a spec and need to match house style, especially the confirm-then-act and config-field conventions a self-update touches.

## data-model.md
The shared pipeline dataclasses in `core/events.py` (`Command`, `Intent`, `SkillResult` incl. `expects_reply`, `ToolCall`, etc.), the tool-schema shape, capability types (calendar/search/weather/timespec), and the two SQLite schemas (`ReminderStore`, `CalendarStateStore`).
Read this when: you need exact field names/types for a record, tool schema, or DB table.

## dependencies.md
External libs and services mapped to where they're used, the per-capability extras layout, models downloaded at install, and the PyInstaller freeze/release flow — including the `os.execv` re-exec target difference between source (`python -m assistant.app`) and frozen binary (`entrypoint.py` + `sys._MEIPASS` chdir).
Read this when: you need to know what a component depends on, or what a self-update re-exec must target under freeze vs. source.

## entry-points.md
Every public interface and how to run/build: daemon and TUI entry, pipeline/orchestrator/skill APIs, the control-channel verbs, the `@@STATE` feed, provider ABCs, `DaemonSupervisor`, and the full config surface. Details the confirm-then-act reply seam, the sign-off/persona layer, and how to add a skill.
Read this when: you are wiring the self-update trigger (spoken intent or control verb), adding a skill, or need the exact confirmation/sign-off/restart entry points and run commands.

## testing.md
How the suite runs (pytest `asyncio_mode=auto`, all-native-stubbed), the fake/mock patterns, a coverage map (notably the `expects_reply` and supervisor-lifecycle tests), the live+replay eval harness, and test-first guidance for a self-update feature.
Read this when: you are writing tests for a new seam or need an existing fake/fixture to copy.

## domain.md
Glossary of the vocabulary — Calcifer/persona, wake/VAD/STT/TTS/barge-in/earcon, skills/intents/tools/confirm-then-act/sign-off, stand-down/arbiter/reminders, search, TUI supervision, and wake-training terms.
Read this when: you hit an unfamiliar term in code or a spec and want its precise meaning.
