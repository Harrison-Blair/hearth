# personal-assistant

Offline-first voice personal assistant. Listens for a wake word, transcribes a
command, routes it (search / reminder / calendar / general LLM answer), and
speaks the response. Everything that can run locally does; remote/cloud is an
optional accelerator behind an interface, never a hard dependency.

The deployment target is an 8 GB Raspberry Pi 5; development and verification
happen on a Linux desktop first. Every device id, model path, and threshold
lives in `config.yaml`, so the Pi port is config-only.

## Status

Phase 3 (first full slice) complete: `python -m assistant.app` speaks a greeting,
then runs the end-to-end loop — wake word (openWakeWord) → record (WebRTC VAD) →
transcribe (faster-whisper) → route (keyphrase) → answer (local LLM via Ollama) →
speak (Piper). Everything runs locally. Earlier phases delivered the scaffolding,
contracts, typed config, audio device auto-detection, and local TTS voice-out.

Skills so far: `ClockSkill` (time/date, via keyphrase routing) and a `general`
LLM-answer fallback. The router is keyphrase-only; the LLM-classifier tier and
`AudioArbiter` land once skill ambiguity / proactive audio makes them necessary
(timers and reminders need that machinery, so they ride with the scheduling phase).

## Setup

The Python version is pinned in `.python-version` (3.12) and managed with
[pyenv](https://github.com/pyenv/pyenv), so nothing is installed into the system
Python:

```bash
pyenv install 3.12              # once, if not already installed
python -m venv .venv            # uses the pinned pyenv interpreter
source .venv/bin/activate
pip install -e ".[dev]"         # core deps + pytest/ruff
python -m assistant.app         # boot, log devices, speak greeting
pytest                          # run tests
```

Per-phase heavy/native dependencies are installed as each phase lands, e.g.
`pip install -e ".[tts]"` (Piper), `.[wake]`, `.[stt]`, `.[vad]`, `.[llm]`, `.[scheduling]`.

**Wake word (openWakeWord):** it hard-pins `tflite-runtime`, which has no
Python 3.12 wheel. We run the ONNX backend instead, so install it without deps
and download the stock models:

```bash
pip install -e ".[wake]"                       # onnxruntime + requests
pip install "openwakeword==0.6.0" --no-deps    # ONNX backend, skip tflite pin
python -c "import openwakeword.utils as u; u.download_models(['hey_jarvis'])"
```

The stock `hey_jarvis` model bootstraps voice-in until the custom
`hey assistant` model is trained (Phase 2a).

### System prerequisites

- **PortAudio** (`sounddevice` backend) — e.g. `pacman -S portaudio` / `apt install libportaudio2`.
- **Ollama** (local LLM, from Phase 3) — install the binary, then pull the model:
  ```bash
  # Arch: sudo pacman -S ollama   |   else: curl -fsSL https://ollama.com/install.sh | sh
  ollama serve                     # start the daemon (or enable the systemd unit)
  ollama pull qwen2.5:3b-instruct  # ~2 GB; the model config.yaml expects
  pip install -e ".[llm]"          # httpx (the async client OllamaProvider uses)
  ```
  `OllamaProvider` health-checks the daemon at boot and degrades clearly (warns,
  keeps listening) if it or the model is absent.

## Configuration

`config.yaml` is the single source of truth. Any value can be overridden by an
`ASSISTANT_*` environment variable (nested keys use a double underscore, e.g.
`ASSISTANT_LLM__MODEL=llama3.2:3b`). Audio `input`/`output` accept `null`
(system default), an integer device index, or a substring of the device name.
