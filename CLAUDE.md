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
`vad`, `llm`, `nlu`, `scheduling`) and installed only as a phase needs them — see
README for the openWakeWord ONNX install quirk and the Ollama/Piper prerequisites.
Tests run without the native extras: anything that touches a model or device is
stubbed, so `pip install -e ".[dev]"` alone is enough to run the suite.

## Architecture

Offline-first voice assistant. The flow is a single async loop in
`assistant/core/pipeline.py`:

> wake word → record (VAD) → transcribe (STT) → route → skill → speak (TTS)

**Interface-per-capability.** Each capability lives in its own package with an
ABC `base.py` and concrete implementation(s) beside it: `wake/`, `stt/`, `llm/`,
`tts/`, `nlu/`, `audio/`, plus stubs for `sync/`, `connectivity/`, `scheduling/`,
`storage/`. `VoicePipeline` depends only on the base classes; it never imports a
concrete provider. **When adding a capability or swapping an implementation, code
against the `base.py` ABC — do not let the pipeline reach for a concrete type.**

**`app.py` is the only wiring point.** It is the composition root: it reads
`Config`, constructs every concrete implementation (`PiperTTS`,
`OpenWakeWordDetector`, `FasterWhisperSTT`, `OllamaProvider`, `KeyphraseRouter`,
skills…), and injects them into `VoicePipeline`. Construction-time choices
(which router phrases, which skills, the default skill) live here, not inside the
components.

**Remote is an optional accelerator, never a hard dependency.** Local
implementations are the guaranteed path; cloud/remote always sits behind an
interface with a local fallback (`connectivity/`, `sync/` are stubs reserving
that seam). Providers health-check at boot and degrade with a clear log warning
rather than crashing (see `OllamaProvider.health()` and the boot check in `app.py`).

**Skills are plug-ins.** A capability = one `Skill` subclass (`skills/base.py`)
declaring `name` + `intents`, registered via `SkillRegistry.register(...)`. The
router emits an `Intent.type` string; the registry maps it to a skill (or the
`default=True` skill). Routing never hard-codes skill names. `KeyphraseRouter` is
tier one (cheap substring match → default intent); an LLM-classifier tier is
planned for when keyphrases become ambiguous.

**`core/events.py` holds the shared dataclasses** (`WakeEvent`, `Command`,
`Intent`, `SkillResult`) that flow down the pipeline. They live in `core/` so the
capability packages can pass them without importing each other — this is the rule
that keeps the dependency graph acyclic. Keep new cross-stage records here.

**Config is the single source of truth** (`core/config.py`, pydantic-settings).
`config.yaml` → typed models; any value is overridable by `ASSISTANT_*` env vars
with `__` for nesting (e.g. `ASSISTANT_LLM__MODEL=llama3.2:3b`). Precedence:
explicit init args > env > `config.yaml`. Every device id, model path, and
threshold is config so the Raspberry Pi 5 deployment is config-only. **Add new
tunables as a typed field on the relevant `*Config` model, mirrored in
`config.yaml` — never hard-code a path, threshold, or device id in a component.**

## Conventions

- All pipeline-facing capability methods are `async`. `pytest` runs in
  `asyncio_mode = auto`, so `async def test_...` works without a marker.
- Components take primitive/config values in `__init__` (paths, thresholds), not
  the whole `Config` object — that keeps them unit-testable in isolation.
- Development is phased (README tracks status); the stub packages and base
  classes are deliberate seams for later phases, not dead code — don't delete them.
