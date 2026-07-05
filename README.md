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
then runs the end-to-end loop — wake word (livekit-wakeword) → record (WebRTC VAD) →
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

**Wake word (livekit-wakeword):** a minimal onnxruntime + numpy runtime with the
mel/embedding models bundled in the wheel — no extra install steps:

```bash
pip install -e ".[wake]"                       # livekit-wakeword
```

The runtime loads the trained `.onnx` classifier(s) named in `config.yaml`
(`wake.model_paths`); train the "Calcifer" model with `training/` (see
`training/README.md`).

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

A Textual terminal UI supervises the daemon as a child process — designed for
the Raspberry Pi's 3.5" touchscreen in **portrait (320×480, ≈40×30 terminal
cells)**, operated by touch alone: one focused screen per job, full-width
tappable buttons, no typing required.

```bash
pip install -e ".[tui]"
python -m tui
```

It does **not** import the native audio/model deps — only the daemon child does.
A **Home** screen shows status at a glance (daemon state, Ollama health, model,
wake phrases, volume) with one-tap navigation and controls (Start/Stop, Restart,
Restart LLM, mute and −/+ volume — volume changes apply instantly over the
child's stdin control channel, no restart). From Home:

- **Logs** — one log pane with three channels: **App** (the daemon's full
  stdout), **LLM** (a labeled call trace of every model round-trip, tagged by
  purpose — `classify` / `timespec` / `answer` / `search`), and **Olma** (the
  LLM server's own diagnostics, streamed live whenever the TUI manages the
  server; an externally-managed Ollama exposes no stdout to capture). On a
  desktop, press `t` for a chat box that injects a typed command into the
  running pipeline *as if it were transcribed speech* (bypasses the wake word),
  so it routes through the real skills and the reply is spoken.
- **Config** — every editable setting as a touch widget: checkbox list for wake
  models, −/+ steppers for numbers (threshold, volume, VAD), full-screen
  pickers for choices (LLM model discovered live, STT model, log level).
  **Save** writes `config.yaml` and restarts; **Apply** relaunches the child
  with `ASSISTANT_*` env overrides only (config.yaml untouched); **Reset**
  re-seeds the form from `default-config.yaml`. A **Restart LLM** button on
  Home (re)starts the LLM server on demand when health is failing — the command
  is `llm.serve_cmd` (default `["ollama", "serve"]`, managed as a child — no
  sudo); systemd users can set it to e.g.
  `["systemctl", "--user", "restart", "ollama"]`.
- **Models** — search the ollama.com registry, tap a result for its description
  and pullable tags, install with streamed progress (queued pulls run in
  order), and browse/delete installed models.

A `.env` file (gitignored; copy `env.example` to start) is still merged into
the daemon's environment at start, under config.yaml's precedence rules — edit
it with any editor; the in-TUI editor was retired with the touch redesign.
