---
generated: 2026-07-15T22:30:28Z
commit: a8489b1afa55662a54ba66548a2e176584a3f387
agent: fledge-forager
fledge_version: 0.5.4
---

# Architecture

How hearth's pieces fit together: the runtime package (`hearth/`), the separate wake-word training pipeline (`training/` → `models/`), and the packaging/release path (`packaging/`, `.github/workflows/release.yml`). Config-driven throughout so the Pi 5 port stays config-only.

## Runtime shape (implemented today)

hearth is a **daemon** (`hearth.app:main` → `hearth = hearth.app:main` entry point) that, once running, exposes a single async orchestration loop reached over a localhost WebSocket ("veneer"). The parts that exist today implement the **text/LLM spine**; the voice pipeline described in CLAUDE.md (audio capture → wake → VAD → STT → … → TTS) is largely roadmap — only the wake-word **training** side (`training/`, `models/`) exists, not the runtime consumer (hearth/app.py, hearth/config.py, hearth/loop.py, training/README.md).

```
WebSocket client (hearth/veneer/client.py)
        │  Request(turn_id, final_user_transcript)
        ▼
hearth/veneer/server.py  Veneer.serve()  ── per-connection session_id
        │  parse_request → run_turn → answer_message/done_message
        ▼
hearth/loop.py  Loop.run_turn()
        │  reconstruct history from EventLog, inject persona system prompt
        ▼
hearth/loop.py  run_react_rounds()  (shared ReAct engine: Thought→Action→Observation)
        │  offers one tool: consult_brain
        ├─► hearth/brain/router.py  Router.select(tier="default") → LocalBackend
        │       (default tier: local Ollama-style backend, no data tools)
        └─► hearth/tools/consult.py  BrainConsult (invoked as the consult_brain tool)
                │  nested run_react_rounds() on tier="tool"
                ▼
            hearth/brain/router.py  Router.select(tier="tool") → RemoteBackend
                │
                ▼
            hearth/tools/registry.py  ToolRegistry → hearth/tools/wikipedia.py
```

Both the top-level orchestrator and the nested brain-consult reuse the same `run_react_rounds()` in `hearth/loop.py` — there is one ReAct implementation, parameterized by which tier/tools it's given (hearth/loop.py:run_react_rounds).

## Two-tier LLM architecture

- **`default` tier** ("Calcifer"/persona) — always `LocalBackend` (hearth/brain/local.py), answers every turn in character, has exactly one tool available: `consult_brain`.
- **`tool` tier** ("brain") — always `RemoteBackend` (hearth/brain/remote.py), used only inside a nested `BrainConsult` round, has access to real data tools (currently `wikipedia_search`).
- Both backends speak an OpenAI-compatible `/chat/completions` protocol via `hearth/brain/openai_compat.py`; `Router._build(tier)` deterministically maps tier → backend class (hearth/brain/router.py).
- Rationale (root.md): local model handles ordinary conversation cheaply/fast; remote model is reserved for tool-calling/research rounds where a stronger model earns its cost.

## Cross-cutting subsystems

- **Config** (`hearth/config.py`) — pydantic-settings `Settings`, precedence init > `HEARTH_*` env > `.env` (secrets only) > `config.yaml` > `default-config.yaml`. Resolves `config.yaml` path from `HEARTH_CONFIG` env, then package-adjacent, then cwd; fails loudly if absent (root.md, hearth.md).
- **Event log** (`hearth/memory/log.py`) — append-only SQLite (`hearth.db`), one row per event (`user_input`, `routing_decision`, `tool_call`, `observation`, `final_answer`, `error`), keyed by `session_id`/`turn_id`. `hearth/memory/reader.py` provides a cursor-based `EventReader` for consumers; `hearth/memory/consumer.py` defines a `Layer2Consumer` protocol + `pull_once()` — a seam for a future Graphiti/FalkorDB indexer, not yet implemented.
- **Transcript** (`hearth/transcript.py`) — best-effort, per-session human-readable log; swallows `OSError` so a disk issue never crashes a turn.
- **Logging** (`hearth/logging_setup.py`) — idempotent root logger setup (guarded by a marker attribute) with `RotatingFileHandler` + optional console handler; websockets' own logger is wired in explicitly.
- **Veneer protocol** (`hearth/veneer/protocol.py`) — a strict serialization whitelist: only `ToolActivity.phase`/`.label` cross the WebSocket boundary. Tool query/arguments/observation content never reaches the client — this is a deliberate opacity boundary, verified by `tests/test_veneer.py`.

## Wake-word training pipeline (separate from the runtime)

`training/` and `models/` form a self-contained subsystem that does **not** share a virtualenv or any package with the runtime (training/README.md, root.md):

```
training/calcifer.yaml (config)
        ▼
training/train.py  run_training()  ──uses──►  livekit-wakeword (training/.venv-train, ROCm torch)
        │   synthesizes positives (Piper VITS) + adversarial negatives,
        │   augments with MUSAN noise / MIT RIRs, trains conv-attention classifier
        ▼
models/wake/calcifer.onnx  (963 KB, exported model artifact)
        +
training/manifest.py  ──writes──►  models/wake/models.json  (fpph, recall, threshold, gate_passed, trained_at)
        │
        └─ manifest.py select <slug>  ──writes──►  config.yaml `wake.model_paths` (regex block edit, preserves comments)
```

`training/train_batch.py` drives `train.py`'s `run_training()` across multiple phrases (`training/phrases.txt`), reusing the one-time ~16 GB data download (ACAV100M, MUSAN, RIRs, Piper voices) across phrases via `--skip-setup` after the first. The only artifact exchanged with the runtime is the `.onnx` file plus the `wake.model_paths`/`wake.threshold` config values — the runtime-side consumer (`hearth/wake/livekit_detector.py` per CLAUDE.md) does not exist yet in `hearth/` (training.md, models.md; open question below).

## Packaging & release

`packaging/build.sh` (invoked by `make release`) builds a PyInstaller single-file binary per architecture (`dist/hearth-$(uname -m)`), bundling `config.yaml` at the bundle root and forcing `--collect-submodules hearth` to catch dynamic imports. `.github/workflows/release.yml` runs this natively on `ubuntu-24.04` (x86_64) and `ubuntu-24.04-arm` (aarch64) matrix runners on `v*` tag pushes (or manual dispatch), smoke-tests the binary (`--version`, DEBUG startup), and attaches both binaries to the GitHub Release via `softprops/action-gh-release` (packaging.md). No cross-compilation — each arch must be built on native hardware.

## Open Questions

- How/when do the audio-facing stages (wake detection, VAD, STT, TTS) integrate with `hearth/loop.py`? Nothing under `hearth/` currently consumes `models/wake/calcifer.onnx` (hearth.md, models.md).
- Where do `aec`/`barge_in`, `scheduling` (apscheduler), `web_search`, `weather`, `calendar` cross-cutting features (named in CLAUDE.md/pyproject extras) actually live? Not present in the current `hearth/` file list (hearth.md).
- `hearth/persona.py:restyle()` is a no-op stub — is persona revoicing (FTHR-011) actively planned next, or blocked on TTS integration (hearth.md)?
