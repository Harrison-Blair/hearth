---
generated: 2026-07-15T22:30:28Z
commit: a8489b1afa55662a54ba66548a2e176584a3f387
agent: fledge-forager
fledge_version: 0.5.4
---

# Context Index

## architecture.md
Diagrams the implemented text/LLM spine (WebSocket veneer → `Loop.run_turn` → shared ReAct engine → two-tier local/remote LLM routing → tool dispatch), the fully separate wake-word training pipeline (`training/` → `models/`), and the packaging/release path. Also names what's still roadmap: no runtime code yet consumes the trained wake-word model or implements audio/VAD/STT/TTS stages.
Read this when: you need the big picture before touching more than one module, or need to know whether a feature (audio, scheduling, calendar, etc.) is implemented yet or still roadmap.

## modules.md
Repo map — one entry per `fledge scan` module (`<root>`, `hearth`, `tests`, `training`, `models`, `packaging`+`.github` merged) with purpose, key files, and a "Look here for" pointer.
Read this when: you're orienting in an unfamiliar part of the repo and need to know which module/files own a given concern before diving into code.

## conventions.md
Reconciled coding/config/process conventions: config precedence and the secrets-in-`.env`-only rule, async-first style, the `BrainError` curated-error pattern, the veneer serialization whitelist, logging idempotency, venv isolation rules, naming/typing patterns, and the fledge (PLM/FTHR) commit taxonomy.
Read this when: writing new code in `hearth/` or `training/` and you need to match existing patterns (error handling, config access, async style, naming), or preparing a fledge-taxonomy commit.

## data-model.md
Every dataclass/pydantic model/persisted schema in the repo: `hearth/config.py` settings tree, the `Brain` protocol types (`Message`, `ToolCall`, `BrainResult`, …), event-log/memory types, the veneer wire-protocol shapes, SQLite/log/transcript storage, and the training-side YAML config + `models.json` manifest schema.
Read this when: you need the exact fields/types of a config object, an event, a wire message, or the training manifest before writing code that constructs or consumes one.

## dependencies.md
Every external library/service in use, split by base runtime deps, the 12 optional `pyproject.toml` extras (and which are excluded from `all`), config-referenced services (Ollama, OpenRouter, Wikipedia REST), the isolated ROCm training-venv stack, and packaging/CI tooling.
Read this when: adding a new dependency, deciding whether something belongs in an existing extra or a new one, or debugging why an extra/service isn't available at runtime.

## entry-points.md
How to run the daemon (`hearth` CLI, `_run_daemon`), the WebSocket veneer's server/client API, the internal orchestration API (`Loop.run_turn`, `run_react_rounds`, `Router.select`, `BrainConsult`), how to build/release binaries (`make release`, the tag-triggered GitHub Actions workflow), the wake-word training CLIs, and the test/lint commands.
Read this when: you need the exact command or function signature to run, build, invoke, or integrate with any part of the system.

## testing.md
pytest setup (`asyncio_mode=auto`, hermetic via `httpx.MockTransport`/websockets doubles), a per-area coverage table mapping each `tests/*.py` file to what it asserts, what's explicitly *not* covered by automated tests (packaging, training, root config standalone), and the manual live-service smoke procedure.
Read this when: adding tests for a change, checking whether a behavior is already covered, or deciding whether a change needs a manual smoke pass (`MANUAL_SMOKE.md`).

## domain.md
Glossary of business/domain vocabulary: persona/brain/tier/consult/ReAct/veneer terms from the runtime, FPPH/recall/threshold/gate/adversarial-negative terms from wake-word training, PyInstaller bundle-root/smoke-test terms from packaging, and the fledge process vocabulary (plumage/feather/fledged/molt evidence).
Read this when: you hit an unfamiliar term in code, commits, or specs and need its precise meaning in this repo's context.
