---
generated: 2026-07-07T07:06:00Z
commit: 02f839d7a116780b02510c2d5b339c23c64a51f5
agent: fledge-forager
fledge_version: unknown
---

# Dependencies

Third-party libraries, external services, and system tools, deduplicated with usage notes. Native/heavy deps are split into per-capability optional extras in `pyproject.toml` (`tts`, `wake`, `stt`, `vad`, `llm`, `nlu`, `scheduling`, `search`, `gcal`, `aec`, `tui`, `dev`, `all`) and installed only as needed. `[all]` includes everything except `aec` and `tui`; the test suite runs on `[dev]` alone with all native deps stubbed.

## Core runtime
- **pydantic ≥2 / pydantic-settings ≥2** — all `*Config` models and env-var override system (`assistant/core/config.py`).
- **pyyaml ≥6** — `config.yaml`/`default-config.yaml` load; also TUI config read/write (lossy of comments) and training config.
- **numpy ≥1.24** — PCM/signal processing (RMS, peak, resampling, earcon synthesis) across `audio/`, `core/`, wake/STT stubs.
- **httpx** — the shared async HTTP client. Used by: Ollama + OpenCode Zen LLM providers, `WikipediaSearch`, `OpenMeteoWeather`, `GoogleCalendar`, and the TUI's Ollama/Zen/registry/voice discovery. **Every network provider test stubs it via `httpx.MockTransport`.**

## Voice I/O (per-capability extras)
- **sounddevice** (+ system **PortAudio**) — audio device enumeration and streaming (`audio/sounddevice_io.py`). `[audio]`-ish; PortAudio is a host prerequisite even for the frozen binary.
- **webrtcvad** — voice-activity detection for end-of-speech (`audio/recorder.py`); `[vad]`. Also needs `setuptools<81` for `pkg_resources`.
- **speexdsp** (optional native, `[aec]`, not in `all`) — acoustic echo cancellation for barge-in (`audio/aec.py`); degrades to passthrough if absent. Needs `libspeexdsp-dev` at build.
- **livekit-wakeword** — ONNX wake-word runtime + bundled mel/embedding models (`wake/livekit_detector.py`); `[wake]`.
- **faster-whisper** (CTranslate2 backend) — local STT (`stt/faster_whisper_stt.py`); `[stt]`. Bundles a Silero VAD ONNX model.
- **piper-tts** (+ system **espeak-ng**) — offline TTS synthesis (`tts/piper_tts.py`); `[tts]`.

## Reasoning / LLM
- **Ollama** (external binary daemon, HTTP at `http://localhost:11434`) — local LLM, the default and guaranteed path; `OllamaProvider` calls `/api/generate`, `/api/chat`, `/api/tags`. Managed/started by `install.sh`, `bootstrap.py`, and the TUI.
- **OpenCode Zen** (external cloud API, OpenAI-compatible, `/zen/v1/...`, Bearer auth) — optional remote LLM accelerator; `OpenCodeZenProvider`. Metadata in `opencode.json`; key kept in `.env`.
- **dateparser** — spoken/absolute date parsing fallback in `nlu/timespec.py`; `[nlu]`.

## Services
- **ddgs** — DuckDuckGo keyless web-search scraper; synchronous, wrapped in `asyncio.to_thread` (`search/ddgs_provider.py`); `[search]`. (Wikipedia search needs only httpx — no extra package.)
- **google-auth** (+ **requests** for its sync transport) — service-account token minting/refresh for Google Calendar; lazy-imported, refreshed off-thread (`calendar/google_calendar.py`); `[gcal]`.
- **apscheduler** — referenced for reminder scheduling background polling (`[scheduling]`); note the runtime `ReminderScheduler` is itself a hand-rolled async poll loop.
- **sqlite3** (stdlib) — reminder and calendar-state stores; WAL + `synchronous=NORMAL`.
- **Open-Meteo** (external free API, no key) — weather forecast + geocoding (`weather/open_meteo.py`).

## Web-search dependency picture (focus area)
Today the search capability depends only on **ddgs** (keyless DuckDuckGo) and **httpx** (Wikipedia). Both are keyless. Introducing AI-first providers (Tavily/Exa/Brave) will add:
- new HTTP calls (reuse **httpx** — the established async client; no new HTTP library needed);
- an **API key** per provider (precedent from `LlmConfig.api_key`/OpenCode Zen: secret lives in `.env`, surfaced via `ASSISTANT_*`, not the touch UI);
- a new optional extra if a provider ships its own SDK (prefer raw httpx to stay consistent and keyless-friendly).
Note: a user memory records interest in a self-hosted **SearXNG** provider (JSON API via `format=json`, needs Redis) as a possible future keyless backend.

## TUI (`[tui]` extra, not in `all`)
- **textual** (~=8.2, pinned for RichLog internals) — the TUI framework (`tui/`).
- **rich** — text styling / RichLog rendering / selection.
- **httpx** — Ollama/Zen/registry/HuggingFace discovery.

## Training (isolated `.venv-train`, never installed into runtime)
- **livekit-wakeword[train,eval,export]** — the training orchestrator.
- **torch + torchaudio** from the **ROCm** index (RX 9070 XT / RDNA4 / gfx1201; ROCm ≥6.4) — GPU compute for VITS synthesis + training. Runtime consumes only the exported `.onnx`; no GPU needed at inference.
- System tools: **espeak-ng, libsndfile, ffmpeg, sox**. Auto-downloaded corpora: ACAV100M, MUSAN, MIT RIRs, Piper voices.

## Packaging (`packaging/`)
- **PyInstaller 6.x** + **pyinstaller-hooks-contrib** — single-file binary build.
- Bundled at build time: **openwakeword 0.6.0** feature models, **piper** assets, **faster_whisper** Silero VAD, **ctranslate2/onnxruntime** binaries, **dateparser** data, **textual** styles; hidden imports include webrtcvad, yaml, sklearn, scipy, apscheduler, tzlocal, tzdata, **ddgs**, huggingface_hub, tokenizers.

## Tooling
- **pytest + pytest-asyncio** (`asyncio_mode = auto`) — test runner; `[dev]`.
- **ruff** (line-length 100) — linter; `[dev]`.
- **pyenv** — pins Python 3.12.13 (`.python-version`); repo requires ≥3.11.

## System prerequisites (host)
PortAudio, Ollama, espeak-ng (per README/`AGENTS.md`); libspeexdsp-dev only if building AEC.

## Licensing
Project is **AGPL-3.0** (`LICENSE`).
