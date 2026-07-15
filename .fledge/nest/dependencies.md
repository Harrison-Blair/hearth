---
generated: 2026-07-15T22:30:28Z
commit: a8489b1afa55662a54ba66548a2e176584a3f387
agent: fledge-forager
fledge_version: 0.5.4
---

# Dependencies

External libraries, tools, and services used across the repo, deduplicated with usage notes. See `pyproject.toml` for exact version pins/extras.

## Base runtime dependencies (always installed)

- **pydantic / pydantic-settings** — `hearth/config.py:Settings`; `YamlConfigSettingsSource`, `env_prefix="HEARTH_"`, `env_nested_delimiter="__"`, `env_file=".env"` (root.md, hearth.md).
- **pyyaml** — config file parsing.
- **sounddevice, numpy** — audio capture primitives (declared as base deps in `pyproject.toml`; not yet exercised by any code in the `hearth/` file list — roadmap per architecture.md).
- **httpx** — `AsyncClient` per LLM backend in `hearth/brain/openai_compat.py`; also raw `httpx.get()` in `hearth/tools/wikipedia.py` (no dedicated Wikipedia client lib).
- **websockets** — server (`hearth/veneer/server.py`) and client (`hearth/veneer/client.py`); its logger is wired into `hearth/logging_setup.py`.

## Optional-dependency extras (`pyproject.toml`, per-phase)

Installed independently so each capability can be opted into (root.md):
- `tts` — piper-tts
- `wake` — livekit-wakeword, onnxruntime
- `stt` — faster-whisper
- `vad` — webrtcvad (pin `setuptools<81`, noted as a required workaround in `pyproject.toml`)
- `llm` — httpx (already a base dep; kept for extra-install symmetry)
- `nlu` — dateparser
- `scheduling` — apscheduler
- `search` — httpx + ddgs
- `gcal` — google-auth, requests, httpx
- `aec` — speexdsp — **deliberately excluded from `all`**: native/build-sensitive, app degrades gracefully when import fails
- `tui` — textual~=8.2 + httpx — **deliberately excluded from `all`**, same reason
- `dev` — pytest, pytest-asyncio, ruff

None of `tts`/`wake`/`stt`/`vad`/`nlu`/`scheduling`/`search`/`gcal`/`aec`/`tui` are consumed by any file in the current `hearth/` module — all roadmap (hearth.md architecture cross-reference).

## Secrets / external services (config-referenced, root.md)

- **Ollama** (local LLM backend) — `http://localhost:11434/v1`, default model `qwen3:14b`.
- **OpenRouter** (remote LLM backend) — `https://openrouter.ai/api/v1`, default model `tencent/hy3:free`; API key via `HEARTH_LLM__OPENROUTER_API_KEY` in `.env`.
- **Wikipedia REST API** — `https://{lang}.wikipedia.org/w/rest.php/v1/search/page`, requires a Wikimedia-policy-compliant User-Agent header; consumed only by `hearth/tools/wikipedia.py`.

## Wake-word training pipeline dependencies (isolated `training/.venv-train`, ROCm)

Never installed alongside the runtime venv (training.md):
- **torch / torchaudio** — ROCm ≥6.4 wheels, pinned to a rocm6.4+ index specifically to avoid pulling CUDA builds on AMD hardware.
- **livekit-wakeword[train,eval,export]** — training orchestrator, wraps the conv-attention/DNN classifier training and ONNX export.
- **pyyaml** — training config loading/dumping.
- System packages (Arch, per `training/bootstrap.sh` warnings): `espeak-ng` (Piper's TTS backend), `libsndfile`, `ffmpeg`, `sox`.
- First-run data downloads (~16 GB, cached under `training/data`, reused via `--skip-setup`): ACAV100M negative-sample embeddings, MUSAN background noise, MIT RIRs, Piper VITS voice models.

`training/manifest.py` is the one training-side script that deliberately depends on stdlib only, so it can run from the repo root without the training venv.

## Packaging / release dependencies

- **PyInstaller** — single-file binary generation, `--collect-submodules hearth` (packaging.md).
- Host build system libraries (Ubuntu, per `.github/workflows/release.yml`): `portaudio19-dev`, `libportaudio2`, `libsndfile1`, `espeak-ng`.
- **GitHub Actions**: `actions/checkout@v4`, `actions/setup-python@v5`, `actions/upload-artifact@v4`, `actions/download-artifact@v4`, `softprops/action-gh-release@v2`.
- **Python 3.12** exact pin at build time (`.python-version` = 3.12.13; CI installs 3.12 via `actions/setup-python`).

## Dev / test tooling

- **pytest** + **pytest-asyncio** (`asyncio_mode=auto`) — see testing.md.
- **ruff** — `ruff check .`, line-length 100 (`pyproject.toml [tool.ruff]`).

## Open Questions

- `sounddevice`/`numpy` are base (non-extra) dependencies despite no current code path using them — confirm whether this is intentional pre-provisioning for the audio-capture stage or accidental scope (root.md).
