# AGENTS.md

See `CLAUDE.md` for the authoritative commands, architecture, and conventions guide.  
This file adds compact, hard-earned context that supplements it.

## Setup gotchas

- `pip install -e ".[dev]"` is enough to run all tests (native deps stubbed).  
- `pip install -e ".[wake]"` installs livekit-wakeword (onnxruntime + numpy,
  mel/embedding models bundled in the wheel — no separate install step).
- `pip install -e ".[tui]"` is **not** included in `[all]` — the TUI must be installed explicitly.
- `vad` extra pins `setuptools<81` because `webrtcvad` imports `pkg_resources`.
- `gcal` extra (httpx, google-auth, requests) powers the Google Calendar skill —
  off by default (`calendar.enabled: false`) and needs a service-account JSON at
  `calendar.credentials_path` plus calendar ids in config.
- System deps: `portaudio` (sounddevice), `ollama` binary, `espeak-ng` (Piper).
- Python is pinned at `3.12.13` via `.python-version`; manage with pyenv.

## Config

- Precedence: **explicit init args > env vars > config.yaml**.  
  Env vars use the `ASSISTANT_` prefix with `__` for nesting (e.g. `ASSISTANT_LLM__MODEL`).
- Audio `input`/`output` accept: `null` (default), `int` (device index), or `str` (name substring match).
- `wake.model_paths` (list, multiple models loaded) > `wake.model_path` > `wake.model_name` (stock fallback).
- Add new tunables as a typed pydantic field on the relevant `*Config` model — never hard-code.

## Architecture (what filenames don't reveal)

- **`app.py` is the composition root.** It constructs every concrete implementation, wires skills into the registry, and injects them into `VoicePipeline`. Construction-time choices live here, not inside components.
- **Routing is the orchestrator's LLM tool-calling loop** (native Ollama tool-calling → prompt-coerced JSON fallback); LLM failure or turn timeout degrades to the default `GeneralSkill`.
- **Reminders and calendar events are proactive.** A background `ReminderScheduler` polls SQLite and a `CalendarWatcher` polls Google Calendar for events starting soon; both announce through `AudioArbiter` which serializes against capture to prevent self-triggering, and both skip polling while `StandDown` is active.
- **`AudioArbiter`** guards the single audio device — capture, TTS playback, and proactive announcements all acquire the same `asyncio.Lock`.
- **`ControlChannel`** reads stdin for line commands from the TUI: `TEXT <utterance>` (inject typed command) and `SET audio.output_volume <float>` (live volume change).
- **Wake phrases are derived from model filenames** via `wake/registry.py`, never hand-maintained. The manifest at `models/wake/models.json` is the authoritative source; otherwise filename stems are prettified.

## Testing quirks

- `pytest-asyncio` runs in `asyncio_mode = auto` — `async def test_...` works without a marker.
- Tests never touch real models or devices (all stubbed). No native deps needed.
- Any non-test code that catches bare `Exception` is intentional — pipeline crashes must not kill the wake loop (see `pipeline.py` broad-except patterns).

## Build / release

- `make release` → `bash packaging/build.sh` builds a single-file PyInstaller binary.  
  **PyInstaller cannot cross-compile** — run on each target arch (x86_64 desktop, aarch64 Pi 5).  
  Output: `dist/assistant-$(uname -m)`.
- CI release workflow (`release.yml`) runs on both `ubuntu-24.04` and `ubuntu-24.04-arm`, triggered by `v*` tags.

## Training wake words

- Custom training lives in `training/` in an **isolated venv** (`training/.venv-train`) — runtime deps conflict with training stack. Never install training deps into the main `.venv`.
- Commands:
  ```bash
  bash training/bootstrap.sh         # one-time: ~18 GB data + venv
  bash training/train.sh --smoke     # quick validation (<1 hr)
  bash training/train.sh             # full run -> models/wake/<model_name>.onnx
  bash training/train_batch.sh       # train multiple phrases from training/phrases.txt
  ```

## Package structure

```
assistant/          # runtime package
  app.py            # composition root (sole wiring point)
  core/             # shared events, config, pipeline, arbiter, control channel
  audio/            # sound I/O, recorder, earcons
  wake/ stt/ llm/ tts/ nlu/ search/ weather/ calendar/   # each has base.py ABC + concrete impl
  skills/           # Skill subclasses, SkillRegistry
  scheduling/       # ReminderScheduler + CalendarWatcher (proactive)
  storage/          # SQLite ReminderStore + CalendarStateStore
  bootstrap.py      # "assistant doctor" provisioning command
tui/                # monitor TUI (separate package, never imported by assistant/)
training/           # custom wake word training (isolated env)
packaging/          # PyInstaller build spec + entrypoint
```

## Style conventions

- Components take **primitive/config values** in `__init__`, never the whole `Config` object.
- All pipeline-facing capability methods are `async`.
- The remaining stub packages (`sync/`, `connectivity/`) and base classes are **deliberate seams** for future capabilities — don't delete them.
- Pipeline code uses bare `except Exception` to avoid crashing on transient errors (device disconnect, synth failure, skill crash). This is intentional.
