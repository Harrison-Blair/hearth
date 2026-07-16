---
generated: 2026-07-15T23:32:23Z
commit: e41ba8a73a56364e7c3bb1acf1332cadab817e45
agent: fledge-forager
fledge_version: 0.5.5
---

# Context Index

## architecture.md
The request path (Veneer → Loop → Router → LLM backend → EventLog), the two-tier local-persona/remote-brain design and its shared ReAct engine, key module seams (brain/, veneer/, memory/), and a verified list of what's actually wired into `hearth/` vs. roadmap-only.
Read this when: you need to understand how a turn flows through the system, how the two LLM tiers relate, or whether a capability (wake word, STT/TTS/VAD/AEC, scheduling) is actually running today.

## modules.md
A repo map of the four scouted areas (`hearth/`, root/packaging/CI, `tests/`, `training/`+`models/`) — each with purpose, key files, and a "look here for" pointer.
Read this when: you're orienting in the repo for the first time, or deciding which top-level area a change belongs in.

## conventions.md
Config/secrets layering and the FTHR-015 secrets-in-.env rule, BrainError's reason/detail split and retry policy, the veneer wire whitelist, async/session-id patterns, logging idempotency, and training-pipeline venv-isolation rules.
Read this when: writing new code and you need to match existing error-handling, config-loading, or async conventions, or before touching anything that crosses the veneer wire.

## data-model.md
Every dataclass/protocol/schema defined in `hearth/` (Brain boundary types, Event/EventLog schema, wire protocol messages, the full pydantic Settings tree) plus the training pipeline's on-disk YAML/JSON formats.
Read this when: adding a field to config, changing what an Event stores, or touching the wire message shapes.

## dependencies.md
Runtime base deps vs. per-capability extras (tts/wake/stt/vad/llm/nlu/scheduling/search/gcal, with aec/tui deliberately excluded from `all`), the two wired external services (Ollama, OpenRouter, Wikipedia), test-only and build/CI deps, and the isolated training-venv dependency set.
Read this when: adding a new dependency, deciding which extra a capability belongs in, or reasoning about what's actually installed on the Pi.

## entry-points.md
Install/run/build/release commands, the CLI and daemon wiring path, the public function-level entry points into each `hearth/` module, and the training pipeline's CLI surface (`train.py`, `train_batch.py`, `manifest.py`).
Read this when: you need the exact command to run/test/build something, or the signature of the function a new caller should invoke.

## testing.md
pytest/asyncio_mode=auto setup, shared conftest.py fixtures and mocking idioms (MockTransport, HostRouter, fake doubles), and a file→feather coverage map across all 19 test files plus the e2e test.
Read this when: writing a new test, figuring out which existing test file covers a `hearth/` module, or deciding what fixture/mock pattern to reuse.

## domain.md
Glossary of assistant/persona vocabulary (Calcifer, brain, consult, tier, ReAct), control-surface/persistence terms (Veneer, whitelist protocol, event log, Layer 2), fledge process terms (PLM/FTHR), and wake-word training vocabulary (FPPH, recall, threshold, gate, slug).
Read this when: you hit an unfamiliar term (in code, commits, or a spec) and need its definition and originating module.
