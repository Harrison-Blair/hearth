---
generated: 2026-07-10T22:45:49Z
commit: ce70f988da5255908dc6a9bb3dc26206b5e57b36
agent: fledge-forager
fledge_version: 0.3.0
---

# Dependencies

External packages and services this repo declares, deduplicated across the runtime's `pyproject.toml`, the training pipeline, and CI, with usage notes.

## Runtime core (`pyproject.toml`, always installed)

- `pydantic` (>=2) — configuration schema validation.
- `pydantic-settings` (>=2) — loads config from YAML + env vars + `.env`.
- `pyyaml` (>=6) — YAML parsing.
- `sounddevice` (>=0.4) — audio I/O device management.
- `numpy` (>=1.24) — array processing (audio frames, embeddings).

## Runtime optional extras (`pyproject.toml`)

Each capability installs independently; `all` = `[tts, wake, stt, vad, llm, nlu, scheduling, search, gcal]` (deliberately **excludes** `aec` and `tui`):

- `tts` — `piper-tts` (speech synthesis; voice `en_US-lessac-medium`).
- `wake` — `livekit-wakeword` (ONNX runtime + bundled mel/embedding models); training itself happens in the separate `training/.venv-train`, never the runtime venv.
- `stt` — `faster-whisper`.
- `vad` — `webrtcvad`, plus `setuptools<81` (webrtcvad imports `pkg_resources`, removed in setuptools 81+).
- `llm` — `httpx` (async client, used by the Ollama provider).
- `nlu` — `dateparser`.
- `scheduling` — `apscheduler`.
- `search` — `httpx` (Wikipedia API), `ddgs` (DuckDuckGo).
- `gcal` — `httpx` (async Calendar v3 REST), `google-auth`, `requests` (sync transport for service-account token minting).
- `aec` (excluded from `all`) — `speexdsp`; native build, requires `libspeexdsp-dev`; app degrades to passthrough if import fails.
- `tui` (excluded from `all`) — `textual~=8.2` (pinned — internals like `RichLog` verified against 8.2.7 specifically), `httpx`.
- `dev` — `pytest`, `pytest-asyncio`, `ruff`.

## External services (from config values)

- **OpenRouter** — primary LLM provider, `openrouter/free` model; requires `ASSISTANT_LLM__OPENROUTER_API_KEY`.
- **Ollama** — local fallback LLM (`qwen3:14b`), started via `serve_cmd: ["ollama", "serve"]`.
- **OpenCode Zen** — alternate LLM provider; requires `ASSISTANT_LLM__OPENCODE_ZEN_API_KEY`.
- **Tavily** — web search provider; requires `ASSISTANT_WEB_SEARCH__TAVILY_API_KEY`.
- **Exa** — web search provider; requires `ASSISTANT_WEB_SEARCH__EXA_API_KEY`.
- **DuckDuckGo / Wikipedia** — free web search sources, no key required.
- **Open-Meteo** — free weather API (forecast + geocoding endpoints).
- **Google Calendar API v3** — via service-account JSON at `~/.config/calcifer/google-service-account.json`.

## Training pipeline dependencies (`training/`, isolated `.venv-train`)

- `livekit-wakeword[train,eval,export]` — full pipeline: data synthesis (Piper VITS + ACAV100M negatives), augmentation (RIRs, MUSAN), `conv_attention` training, eval, `.onnx` export.
- `torch` + `torchaudio` (ROCm build) — targets AMD RDNA4/gfx1201, installed from the rocm6.4 package index in `training/bootstrap.sh`.
- Piper VITS — bundled via `livekit-wakeword`, synthesizes positive + adversarial-negative clips.
- MIT RIRs, MUSAN, ACAV100M — datasets downloaded by livekit into `training/data/` (ACAV100M features are ~16 GB).
- `pydantic-settings` — used at the runtime/training seam by `manifest.py cmd_select`'s `Config().wake.model_refs()` call (this call targets the absent `assistant/` package).
- `PyYAML` — config loading in `train.py`/`train_batch.py`.
- System tools (Arch, per `bootstrap.sh`): `espeak-ng`, `libsndfile`, `ffmpeg`, `sox`.

## CI dependencies (`.github/workflows/release.yml`)

- `actions/checkout@v4`, `actions/setup-python@v5` (Python 3.12), `actions/upload-artifact@v4`, `actions/download-artifact@v4`, `softprops/action-gh-release@v2`.
- apt packages: `portaudio19-dev`, `libportaudio2`, `libsndfile1`, `espeak-ng`.
- Depends on `packaging/build.sh`, which does **not** currently exist on disk — the "Build binary" step would fail today.

## Open Questions

- Whether `onnxruntime` is pulled transitively via `livekit-wakeword` or needs its own runtime-side pin — no direct `onnxruntime` entry visible in `pyproject.toml`'s assigned sections.
