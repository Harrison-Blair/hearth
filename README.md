# personal-assistant

Offline-first voice personal assistant. Listens for a wake word, transcribes a
command, routes it (search / weather / reminder / calendar / general LLM answer), and
speaks the response. Everything that can run locally does; remote/cloud is an
optional accelerator behind an interface, never a hard dependency.

The deployment target is an 8 GB Raspberry Pi 5; development and verification
happen on a Linux desktop first. Every device id, model path, and threshold
lives in `config.yaml`, so the Pi port is config-only.

## Status

`python -m assistant.app` speaks a greeting, then runs the end-to-end loop —
wake word (livekit-wakeword) → record (WebRTC VAD) → transcribe (faster-whisper) →
route/answer (local LLM tool-calling via Ollama) →
speak (Piper). Everything runs locally; the only skills that leave the machine
are web search, weather, and calendar, each degrading to a spoken apology when
their service is unreachable.

Skills: `ClockSkill` (time/date), `ReminderSkill` (reminders + timers),
`WeatherSkill` (Open-Meteo forecasts), `WebSearchSkill` (agentic
DuckDuckGo/Wikipedia search), `CalendarSkill` (Google Calendar — query upcoming
events, create/reschedule/rename/cancel events, set spoken reminders for
events, toggle the calendar watcher, and voice-manage a blocklist of event
titles), `StandDownSkill` ("stand down" / "stop listening" — pauses wake
detection for a spoken duration or indefinitely, until the TUI's Resume button
is tapped), and a `general` LLM-answer fallback.

Reminders/timers persist to SQLite and are spoken **proactively** when due — a
background `ReminderScheduler` polls the store and announces through the
`AudioArbiter`, which serializes the announcement against wake-word capture so
it can't collide or self-trigger. A `CalendarWatcher` announces upcoming
calendar events the same way ("You have *title* in N minutes"), deduped across
restarts. Both pause while standing down. Reminder times are parsed offline by
regex for durations ("in 30 seconds") and by the local LLM for clock times
("at 5 pm"). Missed reminders (app was off when due) are spoken on the next
start.

Routing is a single LLM tool-calling loop: the local model either calls one
skill tool (its arguments become the skill's slots) or answers directly from
general knowledge. If the LLM is unreachable or the turn times out, the
orchestrator degrades to the default general skill, which speaks a clean
"couldn't reach my language model" message, so a reply always comes back.
Conversations are
LLM-steered: after each reply the model decides to keep listening (it asked a
question), check in once with a soft ready-tone, or end — an exact-match
decline ("no", "nope", …) after the tone ends the conversation cleanly
(`conversation.decision_*`, `decline_phrases`). Low-energy captures matching
known whisper artifacts ("thank you", YouTube outros) are dropped as
hallucinations rather than routed.

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

Heavy/native dependencies are split into per-capability extras, installed only
as needed: `pip install -e ".[tts]"` (Piper), `.[wake]`, `.[stt]`, `.[vad]`,
`.[llm]`, `.[nlu]`, `.[scheduling]`, `.[search]`, `.[gcal]` — or `.[all]` for
everything (the TUI's `.[tui]` is deliberately separate).

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
- **Ollama** (local LLM) — install the binary, then pull the model:
  ```bash
  # Arch: sudo pacman -S ollama   |   else: curl -fsSL https://ollama.com/install.sh | sh
  ollama serve                     # start the daemon (or enable the systemd unit)
  ollama pull qwen3:14b            # the model config.yaml expects (see llm.model)
  pip install -e ".[llm]"          # httpx (the async client OllamaProvider uses)
  ```
  `OllamaProvider` health-checks the daemon at boot and degrades clearly (warns,
  keeps listening) if it or the model is absent.

## Configuration

`config.yaml` is the single source of truth. Any value can be overridden by an
`ASSISTANT_*` environment variable (nested keys use a double underscore, e.g.
`ASSISTANT_LLM__MODEL=llama3.2:3b`). Audio `input`/`output` accept `null`
(system default), an integer device index, or a substring of the device name.
`default-config.yaml` documents every key with its default.

**Calendar** (optional, off by default): `pip install -e ".[gcal]"`, create a
Google Cloud service account with the Calendar API enabled, and drop its JSON
key at `calendar.credentials_path`. Share your personal calendar with the
service account read-only and a dedicated "Calcifer" calendar read-write
(events the assistant creates go there), set the two `*_calendar_id`s, and
flip `calendar.enabled: true`. `calendar.blocked_titles` (or the
`calendar.hidden_tag` marker in an event's description) hides noisy events
from queries and announcements; `calendar.watcher_*` tunes the upcoming-event
announcer. `python verify_calendar.py` is a live smoke test of the whole
setup (health check, listing, and a create→rename→delete round-trip).

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
