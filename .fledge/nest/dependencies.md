---
generated: 2026-07-07T02:45:41Z
commit: 8d180f04862c48fdddc61804b81dafcd0f620344
agent: fledge-forager
fledge_version: unknown
---

# Dependencies

External libraries, tools, and services, with where and why each is used. Heavy/native deps are split into per-capability extras in `pyproject.toml` and installed only as needed; the test suite runs on the core + `[dev]` extras alone (everything native is stubbed).

## Core (always installed)

- **pydantic ≥2 + pydantic-settings ≥2** — `Config` loading and validation from `config.yaml` + `ASSISTANT_*` env vars (`assistant/core/config.py`).
- **pyyaml ≥6** — YAML config read/write (config loading; also `tui/configfile.py`).
- **sounddevice ≥0.4** — PortAudio-backed audio I/O (`assistant/audio/sounddevice_io.py`, `devices.py`). Requires system PortAudio (`libportaudio2`).
- **numpy ≥1.24** — PCM/audio math throughout `assistant/audio/` and `assistant/core/pipeline.py` (RMS, int16↔float32).

## Per-capability extras (`pyproject.toml`)

| Extra | Package(s) | Used by / for |
|---|---|---|
| `[tts]` | piper-tts | `assistant/tts/piper_tts.py` — ONNX voice synthesis (needs espeak-ng) |
| `[wake]` | livekit-wakeword | `assistant/wake/livekit_detector.py` — wake detection (bundles onnxruntime + mel/embedding models) |
| `[stt]` | faster-whisper | `assistant/stt/faster_whisper_stt.py` — CTranslate2 Whisper |
| `[vad]` | webrtcvad, setuptools<81 | `assistant/audio/recorder.py` — per-frame VAD (webrtcvad needs pkg_resources) |
| `[llm]` | httpx | `assistant/llm/ollama_provider.py` — async calls to Ollama |
| `[nlu]` | dateparser | `assistant/nlu/timespec.py` — natural-language time parsing |
| `[scheduling]` | apscheduler | reminder/timer scheduling support |
| `[search]` | httpx, ddgs | `assistant/search/ddgs_provider.py` (DuckDuckGo) + `wikipedia.py` |
| `[gcal]` | httpx, google-auth, requests | `assistant/calendar/google_calendar.py` — Google Calendar REST v3 + token refresh |
| `[aec]` | speexdsp | `assistant/audio/aec.py` — echo cancellation (C build; degrades to `None`; excluded from `all` pending Pi 5 validation) |
| `[tui]` | textual~=8.2, httpx | `tui/` (textual pinned to 8.2.x for RichLog internals) |
| `[dev]` | pytest, pytest-asyncio, ruff | test + lint |
| `[all]` | tts, wake, stt, vad, llm, nlu, scheduling, search, gcal | full runtime (aec and tui deliberately excluded) |

## External services / processes

- **Ollama** — local LLM server (`ollama serve`), reached over HTTP by `OllamaProvider` (`/api/generate`, `/api/chat`, `/api/tags`). The default model is `qwen2.5:3b-instruct` (`config.yaml`). The TUI can start/restart/monitor it as a second supervised process and browse the ollama.com registry (`tui/discovery.py`, `tui/supervisor.py`).
- **Google Calendar API v3** — optional; service-account auth via google-auth (sync refresh off-thread), read personal calendar + read/write the dedicated "Calcifer" calendar (`assistant/calendar/google_calendar.py`).
- **DuckDuckGo (via `ddgs`)** — keyless web search; sync client run in `asyncio.to_thread`, fresh client per call; rate-limits, so occasional failures expected (`assistant/search/ddgs_provider.py`).
- **Wikipedia Action API** — keyless; httpx async; lead-paragraph extraction (`assistant/search/wikipedia.py`).
- **Open-Meteo** — keyless forecast + geocoding APIs; WMO code → phrase (`assistant/weather/open_meteo.py`).

## System packages (provisioned by `install.sh`)

PortAudio (`libportaudio2`, `portaudio19-dev`), Ollama binary, espeak-ng (Piper voices), optional `libspeexdsp-dev` (AEC). Pipeline detects pacman vs. apt.

## Models (downloaded at install, not in repo)

- Wake: Calcifer ONNX (~940 KB, `models/wake/calcifer.onnx`) + livekit mel/embedding feature models (in the wheel).
- TTS: Piper ONNX voice from HuggingFace `rhasspy/piper-voices`.
- LLM: pulled by Ollama from ollama.com.
- STT: faster-whisper model cached on first use (distil-small.en recommended for Pi 5).

## Packaging / build & re-exec target

- **PyInstaller 6.\*** + `pyinstaller-hooks-contrib` freezes the app to a single-file binary `dist/assistant-$(uname -m)` (`packaging/assistant.spec`, `build.sh`). No cross-compile: CI builds natively on x86_64 and aarch64 (`.github/workflows/release.yml`), attaching binaries to the GitHub Release via `softprops/action-gh-release@v2`.
- The frozen bundle collects openwakeword, piper, faster_whisper, ctranslate2, onnxruntime, dateparser, textual, apscheduler, huggingface_hub, scikit-learn, scipy.
- **Self-update relevance**: `packaging/entrypoint.py` is the frozen entry point. It detects frozen vs. source (`sys._MEIPASS`), `chdir`s to the bundle root, redirects writable paths via env (`ASSISTANT_STORAGE__DB_PATH`, `HF_HOME`) into an XDG data dir, and routes CLI subcommands (`--version`, `doctor`, `bootstrap`, `tui`, daemon). An `os.execv` re-exec must therefore target **the frozen binary path** when frozen (argv parsed by `entrypoint.py`) or **`sys.executable -m assistant.app`** from source; env vars survive `execv`, but the caller must preserve the chdir/env invariants. Host libs (`libportaudio.so*`, espeak-ng) are resolved from the system, not the bundle.

## Standard library leaned on heavily

`asyncio` (loops, locks, timeouts, subprocess, to_thread), `sqlite3`, `httpx` (async HTTP across LLM/calendar/search/weather/TUI), `threading.Lock` (AEC far-end queue), `hashlib`/`difflib` (eval replay), `logging` (JSONL trace).

## Open Questions

- `[aec]`/speexdsp is excluded from `[all]` pending Pi 5 validation; the validation gate is unspecified (`root` scout).
- google-auth is lazily imported inside async methods; import correctness across all deploy targets (Pi 5, frozen binary) is untested (`assistant-data` scout).
