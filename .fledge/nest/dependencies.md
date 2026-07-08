---
generated: 2026-07-07T22:56:23Z
commit: 58fb2ba9bbeefc5db7d530261bcb3450573048fa
agent: fledge-forager
fledge_version: unknown
---

# Dependencies

External libraries, tools, and services, deduplicated across modules with usage notes. Heavy/native deps are split into per-capability extras in `pyproject.toml` and installed only as needed; the test suite stubs everything native, so `pip install -e ".[dev]"` alone runs it. Python is pinned to **3.12** (`.python-version`); 3.13+ lacks native wheels for scipy/sklearn/onnxruntime/torchaudio and breaks the PyInstaller build.

## Core runtime (always installed)

- **pydantic ≥2 / pydantic-settings ≥2** — `core/config.py` typed config + env override loading.
- **pyyaml ≥6** — parse `config.yaml`/`default-config.yaml`; also TUI config read/write.
- **sounddevice ≥0.4** — PortAudio wrapper for capture/playback (`audio/sounddevice_io.py`).
- **numpy ≥1.24** — PCM int16↔float32 conversion, RMS/peak math, framing (audio, STT, wake).

## Per-capability extras

| Extra | Library | Used by / for |
|---|---|---|
| `tts` | piper-tts (piper, piper.config) | `tts/piper_tts.py` — ONNX voice synthesis; auto-loads `.onnx.json` sidecar |
| `wake` | livekit-wakeword (onnxruntime + bundled mel/embedding models) | `wake/livekit_detector.py` — wake classifier |
| `stt` | faster-whisper (CTranslate2) | `stt/faster_whisper_stt.py` — CPU Whisper; auto-caches HF model |
| `vad` | webrtcvad, setuptools<81 | `audio/recorder.py` — voice-activity endpointing |
| `llm` | httpx | `llm/ollama_provider.py`, `opencode_zen_provider.py` — async HTTP to LLM backends |
| `nlu` | dateparser | `nlu/timespec.py` — natural-language time parsing |
| `scheduling` | apscheduler | scheduling extra (schedulers are asyncio poll loops) |
| `search` | httpx, ddgs | `search/` — DuckDuckGo + AI/keyless HTTP providers |
| `gcal` | httpx, google-auth, requests | `calendar/google_calendar.py` — Calendar v3 REST + service-account token |
| `aec` | speexdsp | `audio/aec.py` — optional acoustic echo cancellation (degrades to None if missing) |
| `tui` | textual~=8.2, httpx | `tui/` monitor (deliberately NOT in `all`) |
| `dev` | pytest, pytest-asyncio, ruff | test + lint |

`all` meta-extra = tts+wake+stt+vad+llm+nlu+scheduling+search+gcal (NOT aec, NOT tui). `rich` ships with Textual (TUI log colorization).

## External services (all optional accelerators behind local fallbacks)

- **Ollama** — local LLM HTTP server (`/api/generate`, `/api/chat`, `/api/tags`, `/api/show`, `/api/pull`, `/api/delete`, `/api/version`) at `host:11434`; the guaranteed local LLM path. Models must be pre-pulled; provisioned by `bootstrap.py` and `install.sh`.
- **OpenCode Zen** — remote OpenAI-compatible gateway (`{base_url}/chat/completions`, `/v1/models`); `OpenCodeZenProvider`. Optional accelerator; requires `ASSISTANT_LLM__API_KEY`. Free model ids end in `-free`.
- **Tavily / Exa** — keyed AI-first web search APIs (`search/tavily.py`, `search/exa.py`, PLM-002); fall back to keyless Wikipedia/DuckDuckGo. Keys via `ASSISTANT_WEB_SEARCH__TAVILY_API_KEY` / `..._EXA_API_KEY`.
- **Wikipedia Action API / DuckDuckGo (`ddgs`)** — keyless search fallbacks.
- **Open-Meteo** — free, keyless forecast + geocoding (`weather/open_meteo.py`).
- **Google Calendar v3** — service-account auth via `google-auth` (lazy import, token refresh in a thread); async httpx for API calls.
- **HuggingFace Hub** — model download/cache for Whisper (STT) and Piper voice catalog.
- **ollama.com / HuggingFace** — scraped/fetched by the TUI for model registry browsing and Piper voice downloads (72h cache).

## Native / system dependencies

- **PortAudio** (`portaudio19-dev`, `libportaudio2`), **libsndfile1**, **espeak-ng** — audio I/O + Piper phonemization (Ubuntu 24.04 build deps).
- **onnxruntime**, **ctranslate2** (+ libgomp) — ONNX/Whisper inference backends bundled in the PyInstaller binary.

## Build & packaging

- **PyInstaller 6.x** + pyinstaller-hooks-contrib — single-file onefile binaries (`packaging/`); UPX disabled (corrupts native `.so`); architecture-native (x86_64 + aarch64 via GitHub Actions matrix on `v*` tags).
- **openwakeword 0.6.0** — installed `--no-deps` at build for bundled fallback wake models.

## Training-only (isolated `.venv-train`, never in the runtime venv)

- **torch, torchaudio (ROCm builds)** — from the ROCm index (`rocm6.4+`, gfx1201/RDNA4); wake-word classifier training. **torchaudio must come from the ROCm index** (see project memory).
- **livekit-wakeword[train,eval,export]** — synthesis/augmentation/training/export pipeline.
- **ACAV100M, MUSAN, MIT RIRs** — multi-GB negative + augmentation datasets (downloaded by livekit setup).
- **MIOpen** (ROCm kernel tuning), **espeak-ng/libsndfile/ffmpeg/sox** — system audio tools.

## Standard library (notable)

`asyncio` (event loop, gather, locks, timeouts), `httpx` (all async HTTP + `MockTransport` in tests), `sqlite3` (WAL storage), `logging`/`logging.handlers` (JSONL + rotation), `json`, `os`/`sys` (`os.execv` restart), `contextlib.asynccontextmanager` (AudioArbiter).

## Notes

- License is **GNU AGPL v3** (network copyleft) — relevant when bundling/serving.
- The `search`, `gcal`, and `llm` extras all pull `httpx`; it is the single shared async HTTP client across LLM, search, weather, calendar, and the TUI.
