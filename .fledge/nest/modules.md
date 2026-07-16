---
generated: 2026-07-15T23:27:05Z
commit: e41ba8a73a56364e7c3bb1acf1332cadab817e45
agent: fledge-forager
fledge_version: 0.5.5
---

# Modules

Repo map: each module, its purpose, key files, and where to look for what.

## `hearth/` — the runtime package

Purpose: the daemon itself — WebSocket control surface, two-tier LLM brain, tools, memory, config.

Key files:
- `app.py` — CLI entry (`main`), daemon wiring (`_run_daemon`)
- `config.py` — `Settings` (pydantic-settings): `LLMConfig`, `VeneerConfig`, `ToolConfig`, `AgentConfig`, `PersonaConfig`, `ConversationConfig`, `StorageConfig`, `LoggingConfig`
- `loop.py` — `Loop.run_turn`, shared ReAct engine `run_react_rounds`
- `persona.py` — Calcifer persona shaping (currently a no-op `restyle` stub, FTHR-011)
- `events.py` — `ToolActivity`, `EventSink`, `null_sink`
- `transcript.py` — per-session human-readable transcript writer
- `logging_setup.py` — one-time rotating file + console handler setup
- `brain/` — LLM backend abstraction: `base.py` (protocol + types), `router.py` (tier→backend selection), `local.py` (Ollama), `remote.py` (OpenRouter), `openai_compat.py` (shared request/response logic), `errors.py` (`BrainError`)
- `veneer/` — WebSocket control surface: `server.py` (daemon), `client.py` (CLI client), `protocol.py` (wire whitelist)
- `memory/` — `log.py` (`EventLog`, append-only sqlite), `reader.py` (`EventReader`, read-only cursor), `consumer.py` (`NoOpConsumer`)
- `tools/` — `registry.py` (`ToolRegistry`), `wikipedia.py` (`wikipedia_search`), `consult.py` (`BrainConsult`, nested ReAct)

Look here for: adding/changing a turn's behavior, adding a new tool, changing LLM backend/tier routing, changing what crosses the WebSocket wire, changing what gets persisted.

## `<root>` — project metadata, config, packaging (merges `.github`, `packaging`)

Purpose: dependency/build/config surface and top-level docs; no runtime logic.

Key files:
- `pyproject.toml` — package metadata, version (`0.1.0`), console script, per-phase extras
- `config.yaml` / `default-config.yaml` — active config / documented reference (same schema)
- `.env.example` — secrets-only template (`HEARTH_LLM__OPENROUTER_API_KEY`)
- `Makefile` — `release` (→ `packaging/build.sh`), `clean`
- `packaging/build.sh` — PyInstaller single-file binary builder (`dist/hearth-$(uname -m)`), `HEARTH_BUILD_EXTRAS` controls baked-in extras
- `packaging/entry.py` — thin PyInstaller entry importing `hearth.app:main`
- `.github/workflows/release.yml` — CI: native build on `ubuntu-24.04` (x86_64) + `ubuntu-24.04-arm` (aarch64), smoke test, upload on `v*` tags
- `README.md`, `CLAUDE.md`, `MANUAL_SMOKE.md` — user docs, dev/agent docs, manual smoke-test procedure
- `.gitignore`, `.python-version` (3.12.13), `LICENSE` (AGPLv3)

Look here for: install/build/release mechanics, what's a secret vs. a config tunable, extras (optional-dependency) definitions, CI behavior.

## `tests/` — test suite

Purpose: hermetic pytest coverage of every wired feather (FTHR-001, 003–011), plus one end-to-end assembly test and a manual (non-hermetic) smoke procedure documented separately in `MANUAL_SMOKE.md`.

Key files:
- `conftest.py` — shared fixtures (`llm_config`, `two_tier_llm_config`, `canned_completion`, `HostRouter`, `make_mock_client`, `_reset_logging_state`)
- `test_e2e_veneer.py` — full stack (real `Veneer`/`Loop`/`Router`/`BrainConsult`/`ToolRegistry`/`EventLog`), all LLM/Wikipedia calls via `httpx.MockTransport`
- one `test_*.py` per `hearth/` seam — see `testing.md` for the full file→feather map

Look here for: how a given `hearth/` module is expected to behave, fixture/mocking patterns for LLM backends and the WebSocket, how to add a test for a new feather.

## `training/` — wake-word training pipeline (merges `models/`)

Purpose: fully synthetic, offline training pipeline that produces the `.onnx` wake-word classifier. Entirely separate from the runtime — isolated venv, no shared imports.

Key files:
- `bootstrap.sh` — one-time `.venv-train` setup (ROCm torch + `livekit-wakeword[train,eval,export]`)
- `calcifer.yaml` — production training config for the "Calcifer" wake word
- `train.py` — single-model training orchestrator, exports `.onnx` to `models/wake/`
- `train_batch.py` — sequential multi-phrase trainer (reads `phrases.txt`)
- `manifest.py` — stdlib-only CLI registry (`upsert`, `list`, `regen`, `select`) over `models/wake/models.json`; `select` is what points `config.yaml`'s `wake.model_paths` at a trained model
- `phrases.txt` — batch-trainer phrase list
- `models/wake/calcifer.onnx` — exported classifier (962 KB binary); **not yet consumed by any code under `hearth/`**
- `models/wake/models.json` — model manifest (recall/fpph/threshold per slug)

Look here for: how the wake-word model is trained/selected, why the training venv must never merge with the runtime venv, what `wake.*` config fields will eventually mean once wired in.

## Open Questions

- None beyond what's carried into `architecture.md` and `domain.md` (the `hearth/wake/` consumer claim, and manifest.py's YAML-parsing robustness).
