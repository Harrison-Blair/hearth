---
generated: 2026-07-17T06:36:02Z
commit: 2cf763f017cef0f330f2fb0df7157c947be1113a
agent: fledge-forager
fledge_version: 0.6.7
---

# Dependencies

External libraries, services, and system packages the repo uses, deduplicated across runtime, training, testing, and packaging, with usage notes.

## Base runtime (always installed)

- `pydantic>=2`, `pydantic-settings>=2` — `Settings` schema, YAML + env-var config loading (`hearth/config.py`).
- `python-dotenv>=1` — loads `.env` secrets into `os.environ` (`load_dotenv()` called explicitly in `app.py`).
- `pyyaml>=6` — YAML parsing for `config.yaml`.
- `httpx` — async HTTP client; one instance per LLM backend + one tool client, built and torn down in `app.py::_run_daemon()`. Used by `hearth/brain/openai_compat.py` (chat completions) and `hearth/tools/wikipedia.py` (Wikimedia REST).
- `websockets` — the veneer WebSocket server (`hearth/veneer/server.py`) and dev client (`hearth/veneer/client.py`); unconditionally imported by `hearth run`.
- `sounddevice>=0.4`, `numpy>=1.24` — audio device bindings; declared as base deps but currently unused by any wired runtime code (roadmap: audio pipeline).

## Optional-dependency extras (13 defined in `pyproject.toml`)

| Extra | Packages | Status |
|---|---|---|
| `tts` | `piper-tts` | roadmap (text-to-speech) |
| `wake` | `livekit-wakeword` | roadmap (runtime consumes only exported `.onnx`, not this package) |
| `stt` | `faster-whisper` | roadmap (speech-to-text) |
| `vad` | `webrtcvad`, `setuptools<81` (pin avoids `pkg_resources` error in setuptools ≥81) | roadmap (voice activity detection) |
| `llm` | `httpx` | wired (explicit per-extra client; redundant with base `httpx`) |
| `nlu` | `dateparser` | roadmap (natural language understanding) |
| `scheduling` | `apscheduler` | roadmap (calendar/scheduling) |
| `search` | `httpx`, `ddgs` | `httpx` wired (Wikipedia); `ddgs` roadmap (DuckDuckGo web search) |
| `gcal` | `httpx`, `google-auth`, `requests` | roadmap (Google Calendar; `google-auth` uses sync `requests` transport for token refresh) |
| `aec` | `speexdsp` (needs system `libspeexdsp-dev`) | roadmap; **excluded from `all`** — native/build-sensitive, app degrades gracefully if import fails |
| `tui` | `textual~=8.2`, `httpx` | roadmap (monitor TUI); **excluded from `all`** — may run separately on Pi; pinned to 8.2.x for widget compatibility |
| `dev` | `pytest`, `pytest-asyncio`, `ruff` | test/lint tooling; **excluded from `all`** |
| `all` | composite: `hearth[tts,wake,stt,vad,llm,nlu,scheduling,search,gcal]` | excludes `aec`, `tui`, `dev` |

## External services (contacted at runtime)

- **Ollama** — local LLM endpoint, default `http://localhost:11434/v1`; serves `llm.tiers.default` (local persona orchestrator).
- **OpenRouter** — free LLM router, default `https://openrouter.ai/api/v1`; serves `llm.tiers.tool` (remote brain); requires `HEARTH_LLM__OPENROUTER_API_KEY`.
- **Wikipedia REST API** (`https://{lang}.wikipedia.org/w/rest.php/v1/search/page`, English default, custom endpoint configurable) — contacted via `httpx` from `hearth/tools/wikipedia.py`, invoked only from the nested `consult_brain` ReAct loop, never directly by the orchestrator.

## Test-only dependencies

- `pytest`, `pytest-asyncio` (`asyncio_mode=auto` — no decorator needed) — the whole suite.
- `httpx.MockTransport` — hermetic backend mocking; per-test handlers return `httpx.Response`.
- `websockets.serve()`/`websockets.connect()` — real (not mocked) in `test_e2e_veneer.py` for genuine end-to-end coverage, on an ephemeral localhost port.
- No real backend (Ollama/OpenRouter/Wikipedia) is ever contacted by the automated suite — that's `MANUAL_SMOKE.md`'s job, run manually against live services.

## Packaging/build/CI dependencies

- **PyInstaller** — single-file binary packing (`packaging/build.sh`, `--onefile`); no pinned version found in repo files.
- **System build packages** (installed via `apt-get` in `.github/workflows/release.yml`): `portaudio19-dev`, `libportaudio2`, `libsndfile1`, `espeak-ng` — needed for audio/TTS support inside the frozen binary (forward-looking: these support the not-yet-wired audio extras).
- **GitHub Actions** — `ubuntu-24.04` (x86_64) and `ubuntu-24.04-arm` (aarch64) runners, native builds only, no cross-compilation.

## Training pipeline dependencies (isolated `.venv-train`, never shared with runtime)

- `livekit-wakeword[train,eval,export]` — the training pipeline itself (generate → augment → train → export → eval), driven via its own CLI module.
- `torch`, `torchaudio` — ROCm 6.4+ wheels (targets AMD RX 9070 XT / RDNA4, gfx1201); bootstrap asserts `torch.version.hip` and `torch.cuda.is_available()`; if RDNA4 kernels are absent, fall back to ROCm 6.5 or 7.x per `training/README.md`.
- `PyYAML` — training config parsing (separate install from runtime's `pyyaml`, since venvs don't share).
- System tools (Arch package names per `bootstrap.sh`): `espeak-ng` (TTS), `libsndfile`/`sox` (audio), `ffmpeg` (video/audio muxing).
- **ACAV100M features, MUSAN backgrounds, MIT RIRs** — livekit-downloaded negative/augmentation datasets (~16 GB on first `setup`, cached under `training/data`).
- **Piper VITS** — TTS voice model livekit uses to synthesize positive wake-phrase clips.

## Open Questions

- What specific version/commit of PyInstaller is pinned or intended? Not constrained in any repo file.

