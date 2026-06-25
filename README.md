# personal-assistant

Offline-first voice personal assistant. Listens for a wake word, transcribes a
command, routes it (search / reminder / calendar / general LLM answer), and
speaks the response. Everything that can run locally does; remote/cloud is an
optional accelerator behind an interface, never a hard dependency.

The deployment target is an 8 GB Raspberry Pi 5; development and verification
happen on a Linux desktop first. Every device id, model path, and threshold
lives in `config.yaml`, so the Pi port is config-only.

## Status

Phase 0 (scaffolding & contracts) complete: typed config, logging, audio device
auto-detection, and all capability interfaces as stubs. `python -m assistant.app`
boots, loads config, logs the chosen audio devices, and exits.

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
`pip install -e ".[tts]"` (Piper), `.[wake]`, `.[stt]`, `.[vad]`, `.[scheduling]`.

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
- **Ollama** (local LLM, from Phase 3) — install separately, then:
  ```bash
  ollama serve
  ollama pull qwen2.5:3b-instruct
  ```
  `OllamaProvider` health-checks the daemon and degrades clearly if it is absent.

## Configuration

`config.yaml` is the single source of truth. Any value can be overridden by an
`ASSISTANT_*` environment variable (nested keys use a double underscore, e.g.
`ASSISTANT_LLM__MODEL=llama3.2:3b`). Audio `input`/`output` accept `null`
(system default), an integer device index, or a substring of the device name.
