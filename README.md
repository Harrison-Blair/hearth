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
transcribe (faster-whisper) → route (LLM classifier, keyphrase fallback) → answer (local LLM via Ollama) →
speak (Piper). Everything runs locally. Earlier phases delivered the scaffolding,
contracts, typed config, audio device auto-detection, and local TTS voice-out.

Skills so far: `ClockSkill` (time/date), `ReminderSkill` (reminders + timers), and
a `general` LLM-answer fallback, all via keyphrase routing. Reminders/timers persist
to SQLite and are spoken **proactively** when due — a background `ReminderScheduler`
polls the store and announces through the `AudioArbiter`, which serializes the
announcement against wake-word capture so it can't collide or self-trigger. Reminder
times are parsed offline by regex for durations ("in 30 seconds") and by the local
LLM for clock times ("at 5 pm"). Missed reminders (app was off when due) are spoken
on the next start. Routing is two-tier: the local LLM classifies each utterance
against the known intents (primary), degrading to cheap keyphrase matching when
the LLM is unreachable so routing keeps working fully offline.

## Setup

The quickest path is the install script, which does everything below (system
packages, venv, deps, models, Ollama) and can optionally install a `--user`
systemd service. Run `./install.sh --help` for per-step flags:

```bash
./install.sh
```

Or set it up manually:

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

## Monitor TUI

A Textual terminal UI supervises the daemon as a child process — handy on the
Raspberry Pi's 3.5" (480×320) touchscreen, where every control is a tappable
button.

```bash
pip install -e ".[tui]"
python -m assistant.tui
```

It does **not** import the native audio/model deps — only the daemon child does.
Tabs plus an `.env` editor, a top status bar (daemon state, model, wake
phrase, volume), and a bottom button row:

- **Logs** — the daemon's full stdout.
- **Ollama** — the LLM server's own diagnostics (model loads, HTTP request logs,
  errors), streamed live whenever the TUI manages the server via **Restart LLM**.
  An externally/systemd-managed Ollama exposes no stdout to capture, so the tab
  shows a hint until you start the server from here.
- **LLM** — a full **labeled call trace** of every model round-trip: the prompt,
  system message, and response for each call, tagged by purpose
  (`classify` / `timespec` / `answer` / `search`) so you see the model's actual
  reasoning, not just the bare intent-classification JSON. Plus a **chat box**:
  type a command and it's injected into the running pipeline *as if it were
  transcribed speech* (bypasses the wake word), so it routes through the real
  skills, reminders fire, and the reply is spoken.
- **Config** — change the LLM/wake model (discovered live), log level,
  thresholds, etc., then **Apply & Restart** to relaunch the child with the new
  `ASSISTANT_*` env. A volume row gives **instant mute / 25–100%** with no
  restart (sent live over the child's stdin control channel). The status bar
  shows a live **Ollama health** badge; a **Restart LLM** button (re)starts the
  LLM server on demand when health is failing and streams its output into Logs.
  The command is `llm.serve_cmd` (default `["ollama", "serve"]`, managed as a
  child — no sudo); systemd users can set it to e.g.
  `["systemctl", "--user", "restart", "ollama"]`.
- **Env** — edit a `.env` file in place (merged into the daemon's environment at
  start, under config.yaml's precedence rules), with one-tap **Add missing from
  `env.example`** / **Remove values not in `env.example`**. Copy `env.example` to
  `.env` to get started; `.env` is gitignored.

Config changes are applied as `ASSISTANT_*` env overrides on restart — the TUI
never rewrites `config.yaml`.
