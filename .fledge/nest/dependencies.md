---
generated: 2026-07-08T00:34:07Z
commit: 0a67e65dc3d33b2e9c911f1296eef515124fa678
agent: fledge-forager
fledge_version: unknown
---

# Dependencies

External libraries, tools, and services, with what uses each. Declared in `pyproject.toml` (Python ≥ 3.11; `.python-version` pins 3.12.13). Heavy/native deps are split into per-capability extras and installed only as needed; `.[dev]` alone runs the test suite because native deps are stubbed.

## Core (always installed)
- **pydantic ≥ 2 / pydantic-settings ≥ 2** — config schema, validation, env/YAML loading (`assistant/core/config.py`).
- **pyyaml ≥ 6** — `config.yaml`/`default-config.yaml` parsing (daemon + `tui/configfile.py`).
- **sounddevice ≥ 0.4** — PortAudio-backed audio I/O (`assistant/audio/sounddevice_io.py`); requires system `libportaudio2`.
- **numpy ≥ 1.24** — PCM/array ops across audio, wake, earcons, processing.

## Per-capability extras
- **`[llm]` → httpx** — async HTTP for `OllamaProvider` and `OpenAICompatibleProvider`; pooled `AsyncClient` per provider. Also used by search, weather, calendar, and TUI discovery.
- **`[tts]` → piper-tts** — ONNX voice synthesis (`assistant/tts/piper_tts.py`); needs system `espeak-ng`.
- **`[wake]` → livekit-wakeword** — ONNX wake-word detection (`assistant/wake/livekit_detector.py`); bundles onnxruntime + mel/embedding models.
- **`[stt]` → faster-whisper** — Whisper STT via CTranslate2 (`assistant/stt/faster_whisper_stt.py`); model auto-downloads from HuggingFace.
- **`[vad]` → webrtcvad, setuptools<81** — end-of-speech VAD (`assistant/audio/recorder.py`); setuptools pinned because webrtcvad imports `pkg_resources` at module top.
- **`[nlu]` → dateparser** — reminder/time parsing (`assistant/nlu/timespec.py`).
- **`[scheduling]` → apscheduler** — proactive poll loops (`assistant/scheduling/`).
- **`[search]` → httpx, ddgs** — DuckDuckGo + Wikipedia keyless search plus keyed Tavily/Exa (`assistant/search/`).
- **`[gcal]` → httpx, google-auth, requests** — Google Calendar service-account auth + async REST (`assistant/calendar/google_calendar.py`); lazy-imported so it's off by default.
- **`[aec]` → speexdsp** — Speex echo cancellation for barge-in (`assistant/audio/aec.py`); NOT in `[all]` until Pi validation; degrades to passthrough if the native lib is missing.
- **`[tui]` → textual ~8.2, httpx** — the monitor TUI; deliberately separate from `[all]` (textual pinned for RichLog internals used by `tui/collapse.py`).
- **`[dev]` → pytest, pytest-asyncio, ruff** — tests (asyncio_mode auto) + lint (line-length 100).
- **`[all]`** — tts/wake/stt/vad/llm/nlu/scheduling/search/gcal, but NOT tui.

## Standard-library heavy hitters
- **httpx** internals aside, the code leans on `asyncio`, `sqlite3` (WAL stores), `json`, `logging`, `pathlib`, `time` (monotonic for timeouts/circuit-breakers), `random` (retry jitter, canned-variant selection), `re`, `datetime`, `importlib.util` (loading training scripts in tests).

## External services (optional, with local fallbacks)
- **Ollama** — local LLM daemon; primary or fallback provider (`OllamaProvider`, health via `/api/tags`). Default local model `qwen2.5:3b-instruct`; `config.yaml` uses it as the fallback (`qwen3:14b` in the active profile, `qwen2.5:3b-instruct` in defaults).
- **OpenRouter** — remote LLM gateway, current primary; `provider: openrouter`, `model: openrouter/free`, base `https://openrouter.ai/api/v1`. Requires `ASSISTANT_LLM__API_KEY` (no anonymous tier).
- **OpenCode Zen** — alternate OpenAI-compatible gateway (`opencode-zen`, base `https://opencode.ai/zen/v1`); preserved in `GATEWAYS` and as a commented profile. (`opencode_zen_provider.py` no longer exists — served by the generic provider.)
- **Open-Meteo** — free keyless weather + geocoding (`assistant/weather/open_meteo.py`).
- **DuckDuckGo (ddgs)** — keyless search; **Wikipedia** — keyless search; **Tavily** / **Exa** — optional keyed AI-search (keys via `ASSISTANT_WEB_SEARCH__TAVILY_API_KEY` / `__EXA_API_KEY`).
- **Google Calendar v3** — optional; service-account JSON + calendar ids.

## Tooling & packaging
- **PyInstaller 6.\*** + pyinstaller-hooks-contrib — frozen single-file binaries (`packaging/`); bundles onnxruntime, ctranslate2, faster_whisper, piper (espeak bridge), webrtcvad, apscheduler, dateparser, textual. `openwakeword 0.6.0` installed `--no-deps` (tflite wheel unavailable) as a build-only feature-model source.
- **GitHub Actions** (`.github/workflows/release.yml`) — builds x86_64 + aarch64 natively on `v*` tags (no cross-compile).
- **System prerequisites:** PortAudio (`libportaudio2`/`portaudio19-dev`), `espeak-ng` (Piper), `libsndfile1`, and for `[aec]` `libspeexdsp-dev`.

## Training-only (isolated `.venv-train`)
- **livekit-wakeword[train,eval,export]**, **torch/torchaudio (ROCm)** — GPU training for the calcifer wake model; `training/bootstrap.sh` installs torch from the ROCm wheel index (RDNA4/gfx1201 needs ROCm ≥ 6.4). Runtime never imports torch — it consumes only the exported `.onnx`. Data sources downloaded on first run: ACAV100M negatives (~2000 h), MUSAN noise, MIT RIRs, a Piper voice.

## Test doubles instead of real deps
Tests replace every native/network dependency: `httpx.MockTransport` for all HTTP providers, `sys.modules["speexdsp"]=None` / monkeypatched `PiperVoice.load` / injected `FakeWakeWordModel` for native libs, `:memory:` SQLite for stores, and scripted LLM fakes (`ScriptedLLM`, `ReplayProvider`) for the orchestrator. See `testing.md`.
