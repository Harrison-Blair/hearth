---
generated: 2026-07-17T06:36:02Z
commit: 2cf763f017cef0f330f2fb0df7157c947be1113a
agent: fledge-forager
fledge_version: 0.6.7
---

# Context Index

## architecture.md
The request path (Veneer → Loop → Router → LLM backends → EventLog), the daemon startup wiring order in `app.py::_run_daemon()`, the two-tier brain pattern (local persona orchestrator + remote brain via shared `run_react_rounds` ReAct engine), the veneer wire-protocol security whitelist, a module dependency graph, and the current wired-vs-roadmap boundary.
Read this when: you need the big picture of how components connect, are planning the audio-veneer addition or the veneer→chat rename, or need to know what's actually wired into the runtime versus roadmap-only.

## modules.md
Repo map: every module `fledge scan` reports (root, hearth split into 4 concern areas, tests, training, misc), each with purpose, key files, and "look here for" pointers — including the full list of "veneer" naming references that a rename to `chat` would need to touch.
Read this when: you need to find which file(s) own a given responsibility, or need the concrete rename-to-`chat` reference checklist.

## conventions.md
Reconciled cross-module conventions: async-first architecture, the YAML-tunables/`.env`-secrets split, frozen module boundaries (Loop↔Veneer, Brain protocol), error normalization + graceful degradation, retry policy, logging conventions, fledge commit taxonomy/test-first discipline, and the training-pipeline venv-isolation pattern.
Read this when: writing new code and need to match existing idiom, or deciding how a new subsystem (e.g. an audio veneer) should isolate itself the way brain/veneer/training already do.

## data-model.md
Every schema/struct in the runtime: the full 8-section `Settings` config schema, the frozen `Brain` boundary types (`Message`, `ToolCall`, `ToolSpec`, `BrainResult`, `BrainError`), the sqlite `events` table schema, the veneer wire-protocol dataclasses, and the wake-word training manifest JSON shape.
Read this when: adding or changing a config field, touching the Brain protocol, or working with the event log or the training manifest.

## dependencies.md
All third-party libraries and external services, deduplicated with usage notes: base runtime deps, all 13 `pyproject.toml` extras (which are wired vs. roadmap), Ollama/OpenRouter/Wikipedia as contacted services, test-only deps, packaging/CI deps, and the isolated training-pipeline deps (ROCm PyTorch, livekit-wakeword).
Read this when: deciding which extra a new capability belongs in, evaluating a new dependency, or tracing what a build/CI step actually installs.

## entry-points.md
How to run and build hearth: the `hearth run` CLI, config-loading precedence, the veneer WebSocket wire protocol (inbound/outbound message shapes), `make release`/CI release flow, and the training-pipeline CLIs (`train.py`, `train_batch.py`, `manifest.py select`).
Read this when: you need exact commands to run/build/test the project, or the precise wire-protocol message shapes for veneer work.

## testing.md
Test framework and conventions (pytest, `asyncio_mode=auto`, hermetic mocking via `httpx.MockTransport`/`websockets` doubles), shared fixtures/doubles in `conftest.py`, and a full source-module → test-file coverage map, plus the two tests that enforce the security boundaries (no-tool-internals-on-wire, no-API-key-leak).
Read this when: adding tests for a change, or checking whether a module already has coverage before extending it.

## domain.md
Glossary of business/domain vocabulary: the two-tier brain terms (tier, backend, ReAct, consult_brain, guard prompt), veneer/turn/session/tool-activity terms, Layer-2/event-log terms, wake-word training vocabulary (FPPH, gate, manifest, adversarial negatives), fledge process terms — plus a reconciliation note on the inconsistent Vesta/Calcifer/Prometheus persona-vs-wake-word naming found across scout reports.
Read this when: you're unsure what a term in code, config, or commit messages means, or need to understand the current (inconsistent) persona/wake-word naming before the audio-veneer plumage locks in terminology.
