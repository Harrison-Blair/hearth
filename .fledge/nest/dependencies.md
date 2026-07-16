---
generated: 2026-07-15T23:27:05Z
commit: e41ba8a73a56364e7c3bb1acf1332cadab817e45
agent: fledge-forager
fledge_version: 0.5.5
---

# Dependencies

External libraries, tools, and services, deduplicated across the runtime, test, and training modules, with usage notes. See `pyproject.toml` for the authoritative extras split — comments there explain each pin.

## Runtime — base (always installed)

- **pydantic>=2, pydantic-settings>=2** — `hearth/config.py` `Settings` schema and layered source precedence.
- **python-dotenv>=1** — loads `.env` secrets.
- **pyyaml>=6** — parses `config.yaml`.
- **httpx** — async HTTP client; one instance per LLM backend (`hearth/brain/local.py`, `remote.py`) plus one for Wikipedia (`hearth/tools/wikipedia.py`); `response.raise_for_status()` surfaces HTTP errors.
- **websockets** — `hearth/veneer/server.py` (async `serve`), `hearth/veneer/client.py` (`connect`); `ping_interval=None` deliberately (see `conventions.md`).
- **sounddevice, numpy** — present in base specifically to avoid import-time failures elsewhere, per `pyproject.toml` comments; not otherwise exercised by the wired runtime.

## Runtime — optional extras (`pip install -e '.[extra]'`)

Split per capability so each installs independently:

- `tts` — piper-tts (roadmap, Phase 1+).
- `wake` — livekit-wakeword, onnxruntime (roadmap; training-time only today — see `architecture.md`).
- `stt` — faster-whisper (roadmap).
- `vad` — webrtcvad (pins `setuptools<81` to dodge `pkg_resources` removal; roadmap).
- `llm` — httpx (redundant with base, listed for clarity).
- `nlu` — dateparser (roadmap).
- `scheduling` — apscheduler (roadmap).
- `search` — httpx, ddgs — backs the currently-wired Wikipedia tool plus future DuckDuckGo search.
- `gcal` — httpx, google-auth, requests (roadmap).
- `aec` — speexdsp (needs system `libspeexdsp-dev`); **deliberately excluded from `all`** — app must degrade gracefully if this import fails.
- `tui` — textual~=8.2, httpx; **deliberately excluded from `all`** — separate child process.
- `all` = `[tts, wake, stt, vad, llm, nlu, scheduling, search, gcal]` (excludes `aec`, `tui`).
- `dev` — pytest, pytest-asyncio, ruff.

## External services

- **Ollama** — local LLM, default backend for the `default` tier (`http://localhost:11434/v1`).
- **OpenRouter** — remote LLM, default backend for the `tool` tier (`https://openrouter.ai/api/v1`); requires `HEARTH_LLM__OPENROUTER_API_KEY`.
- **Wikipedia REST API** (`en.wikipedia.org/w/rest.php/v1/search/page`) — the only currently-wired data tool.

## Test-only dependencies

- **pytest, pytest-asyncio** — `asyncio_mode=auto` (async `def test_*` needs no decorator); confirmed in `pyproject.toml` and exercised throughout `tests/`.
- **httpx.MockTransport** — hermetic stubbing of every LLM/Wikipedia call; paired with a `HostRouter` conftest fixture that branches by request host for deterministic multi-backend assertions.
- **websockets test doubles** — `FakeWebSocket` for unit-level veneer error tests; real `websockets.serve()` only in `test_e2e_veneer.py`.

## Build/CI dependencies

- **PyInstaller** — `packaging/build.sh` produces `dist/hearth-$(uname -m)`; `HEARTH_BUILD_EXTRAS` env var controls which extras get baked in (default `all`); `--add-data config.yaml:.` lands the config at `sys._MEIPASS`; `--collect-submodules hearth` covers function-level imports PyInstaller's static analysis would otherwise miss.
- **GitHub Actions** (`.github/workflows/release.yml`) — native build matrix on `ubuntu-24.04` (x86_64) and `ubuntu-24.04-arm` (aarch64); no cross-compilation.

## Training-pipeline dependencies (isolated venv, never merged with runtime)

- **livekit-wakeword[train,eval,export]** — full ONNX wake-word pipeline (`setup` downloads data, `run` executes training stages).
- **torch, torchaudio** (ROCm builds, `rocm6.4` index) — installed by `training/bootstrap.sh` for RDNA4/gfx1201 GPUs; asserts HIP availability.
- **PyYAML** — used by `train.py`, `train_batch.py`, `manifest.py` to read/write training configs and to hand-edit `config.yaml`'s `wake.model_paths`.
- **Piper VITS** (via livekit) — synthesizes positive/negative training clips.
- **ACAV100M, MUSAN, MIT RIRs** (livekit-managed downloads) — negative training set, background noise, and room-impulse-response augmentation data, respectively.
- **System packages** (Arch, per `bootstrap.sh`) — `espeak-ng`, `libsndfile`, `ffmpeg`, `sox`.

## Open Questions

- None beyond the general extras-vs-roadmap wiring gap already tracked in `architecture.md`.
