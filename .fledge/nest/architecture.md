---
generated: 2026-07-10T22:45:49Z
commit: ce70f988da5255908dc6a9bb3dc26206b5e57b36
agent: fledge-forager
fledge_version: 0.3.0
---

# Architecture

How hearth's pieces fit together, and — critically — which of those pieces currently exist on disk versus exist only as references in tracked files.

## Repo state: mid-restart

This repo is mid-restart (`git log`: `ce70f98 restarting (again)`). Only these survived: `config.yaml` / `default-config.yaml`, `models/wake/calcifer.onnx` (+ `models/wake/models.json`), `training/`, `pyproject.toml`, `Makefile`, `.github/workflows/release.yml`, `.env.example`, `pluma/` (empty fledge scaffolding). **The runtime source tree is absent**: `assistant/` (the actual daemon — wake/recorder/stt/llm/agent/verify/persona/tts pipeline), `tui/` (Textual monitor), and `packaging/build.sh` (invoked by `make release`) do not exist on disk (raw/root.md Open Questions; raw/models.md Open Questions). `pyproject.toml`'s entry point `assistant = assistant.app:main` (`pyproject.toml:45`), CLAUDE.md's architecture description, and the config files all reference this absent tree as if it were live — treat them as **the intended design**, not a working contract, until `assistant/` is recreated. `.github/workflows/release.yml`'s "Build binary" step calls `packaging/build.sh`, which would fail today since that script doesn't exist.

## Intended runtime pipeline (from config, not yet code)

A staged voice cascade, each stage one config section in `config.yaml` / `default-config.yaml`:

`audio` (capture, device/sample-rate) → `wake` (livekit-wakeword ONNX detector against `models/wake/calcifer.onnx`) → `recorder` (WebRTC VAD endpointing) → `stt` (faster-whisper) → `llm` (pluggable provider) → `agent` (tool-calling rounds) → `verify` (pre/post answer-checking loop) → `persona` (revoice in Calcifer's voice) → `tts` (piper).

Cross-cutting sections: `conversation` (follow-up window, history), `scheduling` (apscheduler), `web_search` (ddgs + Wikipedia, optionally Tavily/Exa), `weather` (Open-Meteo), `calendar` (Google service-account, async httpx), `storage` (sqlite `assistant.db`), `aec`/`barge_in` (echo cancellation + wake-word interrupt, both off by default), `logging` (rotating file logs under `logs/`).

LLM provider is pluggable: `ollama` (local fallback, `qwen3:14b`), `openrouter` (primary, `openrouter/free`), `opencode_zen`, with an explicit `fallback`/`fallback_model` pair (`config.yaml` llm section).

## Training pipeline is architecturally separate

`training/` (see `testing.md`/`entry-points.md` for commands, `domain.md` for vocabulary) is a fully self-contained wake-word training system with its own venv (`training/.venv-train`, ROCm torch + livekit-wakeword) that **must never share the runtime venv** (CLAUDE.md; `training/bootstrap.sh`). The only artifact that crosses the boundary into the runtime's world is the exported `.onnx` file under `models/wake/`, plus its `models.json` metadata sidecar. `training/manifest.py select` is the handoff point: it writes `config.yaml`'s `wake.model_paths` and round-trips through the (currently absent) runtime's `Config().wake.model_refs()` to verify (`training/manifest.py:120-121` — this verification call cannot currently execute since `assistant/` isn't on disk).

## Build & release architecture

`make release` → `packaging/build.sh` (absent) → single-file PyInstaller-style binary `dist/assistant-$(uname -m)`, one native build per target arch (x86_64, aarch64), no cross-compile (`Makefile`, CLAUDE.md). `.github/workflows/release.yml` automates this on `v*` tags (or manual `workflow_dispatch`): a matrix job (`ubuntu-24.04`, `ubuntu-24.04-arm`, `fail-fast: false`) builds, smoke-tests (`--version` + DEBUG-level import check), and uploads artifacts, then a release job (`if: startsWith(github.ref, 'refs/tags/')`) consolidates them into a GitHub Release.

## Configuration architecture

Two-file model loaded via `pydantic-settings`: `config.yaml` (active) and `default-config.yaml` (documented reference/defaults, same schema). Override mechanisms: YAML base → `ASSISTANT_*` env vars (double-underscore nesting, e.g. `ASSISTANT_LLM__MODEL`) → `.env` (secrets only). See `data-model.md` for the section-by-section schema shape and `conventions.md` for the secrets-separation rule.

## Fledge development-process architecture

The repo itself is developed through fledge (bird/nest taxonomy — see `domain.md`): `pluma/plumage/` and `pluma/feathers/` are the (currently empty) planning directories where epics (PLM-xxx) and work units (FTHR-xxx) will live. `.fledge/` holds the tool's own skills/templates/working state and is gitignored except for its skill definitions.

## Open Questions

- When/how will `assistant/`, `tui/`, and `packaging/build.sh` be restored — same repo or elsewhere?
- Does the (absent) runtime's wake detector reload `wake.threshold` automatically after `manifest.py select`, or is that a manual step? `training/README.md` says "set wake.threshold in config.yaml and restart daemon" but `select` only writes `model_paths`.
