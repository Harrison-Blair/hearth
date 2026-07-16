# hearth

An offline-first voice personal assistant — themed around **Vesta**, the
calm, steady presence of the hearth.

That's the goal. **The current build is a text-driven spine**, not yet a voice
assistant: you talk to it by typing, over a small localhost control surface. The
audio side — wake word, speech-to-text, text-to-speech — is groundwork in
progress, not wired into the runtime yet.

## Status / current state

| Working today | Roadmap (not yet in the runtime) |
| --- | --- |
| `hearth` daemon + WebSocket "veneer" control surface | Audio capture → wake word → STT → TTS voice pipeline |
| Two-tier LLM: local persona (Vesta) + remote "brain" | Raspberry Pi 5 target (config-driven device/model/threshold) |
| Wikipedia tool via a nested ReAct loop | Scheduling, calendar, weather, web search extras |
| sqlite event log + per-session transcripts | Wake-word detector consuming `models/wake/calcifer.onnx` |

The wake model (`models/wake/calcifer.onnx`) and the training pipeline under
`training/` already exist — they're the wake-word groundwork — but nothing in the
current runtime consumes them yet.

## Description

hearth is built around a **two-tier LLM design**:

- A **local persona orchestrator** answers every turn *as Vesta* — calm, warm,
  measured, in the first person. It runs on a local model (Ollama `qwen3:14b` by
  default) and has exactly one tool.
- That tool, **`consult_brain(query)`**, routes to a **remote "brain"** (OpenRouter
  by default) whenever Vesta needs a fact she doesn't know. The brain is a plain
  research subsystem, kept in its lane by a `brain_guard_prompt`, and its answer is
  folded back into Vesta's voice.
- The brain can reach for a **Wikipedia** tool through a nested ReAct loop to ground
  its answers in real content.

Which model serves which role is entirely config-driven (`llm.tiers`), so you can
run fully local, fully remote, or split. Turns and routing decisions are recorded
to a sqlite event log, with optional per-session transcripts.

You interact with the daemon through the **veneer** — an asyncio WebSocket control
surface bound to localhost — using the bundled client.

```
client ⇄ veneer → persona (local LLM) ──consult_brain──▶ brain (remote LLM) → wikipedia
                     │                                                            │
                     └────────────── answer in Vesta's voice ◀────────────────┘
```

## Quickstart

```bash
# 1. Install (Python 3.12)
python3 -m venv .venv && .venv/bin/pip install -e '.[all]'
source .venv/bin/activate

# 2. Local tier: start Ollama and pull the configured model
ollama serve &          # skip if already running as a service
ollama pull qwen3:14b

# 3. Remote tier (optional): add an OpenRouter key for consult_brain
cp .env.example .env
#   then edit .env and set HEARTH_LLM__OPENROUTER_API_KEY=sk-...
#   OR skip the key entirely and set  llm.tiers.tool: local  in config.yaml

# 4. Run the daemon, then talk to it from a second terminal
hearth run                          # terminal 1
python -m hearth.veneer.client      # terminal 2
```

In the client, type a plain question like `what's 2 plus 2`, then one that needs a
fact, like `who was Ada Lovelace` — the latter triggers a `…search` (Wikipedia)
activity line before the answer. See **[`MANUAL_SMOKE.md`](MANUAL_SMOKE.md)** for
the fuller against-real-services smoke procedure.

## Installation

- **Python 3.12** — pinned to `3.12.13` via `.python-version` (`pyproject.toml`
  requires `>=3.11`).
- **Editable install** with extras:
  ```bash
  pip install -e '.[all]'    # runtime
  pip install -e '.[dev]'    # test/lint tooling
  ```
- **System libraries** for the native audio deps pulled in by `all`
  (Debian/Ubuntu, from CI):
  ```bash
  sudo apt-get install -y portaudio19-dev libportaudio2 libsndfile1 espeak-ng
  ```
  The text spine itself doesn't exercise these — it needs **Ollama** running (local
  tier) and, for `consult_brain`, an **OpenRouter** API key (remote tier). Both are
  external prerequisites.

### Dependencies

Dependencies are split into per-capability extras in `pyproject.toml`. The `all`
extra is `tts, wake, stt, vad, llm, nlu, scheduling, search, gcal`.
**`aec`, `tui`, and `dev` are deliberately excluded from `all`** — they're
native/build-sensitive and the app degrades gracefully when their imports fail.
The control surface itself needs no extra: `websockets` and `httpx` are base
dependencies, always installed.

| Extra | Installs | Used by the text spine today? |
| --- | --- | --- |
| `llm` | `httpx` | ✅ Ollama / OpenRouter client |
| `search` | `httpx`, `ddgs` | ✅ Wikipedia (ddgs is roadmap) |
| `wake` | `livekit-wakeword` | ⏳ roadmap (voice) |
| `stt` | `faster-whisper` | ⏳ roadmap (voice) |
| `tts` | `piper-tts` | ⏳ roadmap (voice) |
| `vad` | `webrtcvad` (pins `setuptools<81`) | ⏳ roadmap (voice) |
| `nlu` | `dateparser` | ⏳ roadmap |
| `scheduling` | `apscheduler` | ⏳ roadmap |
| `gcal` | `google-auth`, `requests`, `httpx` | ⏳ roadmap |
| `aec` | `speexdsp` (needs `libspeexdsp-dev`) | ⏳ roadmap; **not in `all`** |
| `tui` | `textual~=8.2`, `httpx` | ⏳ roadmap; **not in `all`** |
| `dev` | `pytest`, `pytest-asyncio`, `ruff` | dev only; **not in `all`** |

The comments in `pyproject.toml` record the reason for each pin — read them before
touching deps.

## Configuration

Two files, both loaded via `pydantic-settings`:

- **`config.yaml`** — the active config the daemon loads.
- **`default-config.yaml`** — a reference copy with the same schema and a comment on
  every field. Read it to learn what a knob does.

**Secrets rule:** API keys live in **`.env` only** (never in the YAML). Copy
`.env.example` → `.env` and fill in the keys you use. Non-secret tunables (models,
hosts, thresholds) stay in `config.yaml`.

**Env overrides** use the `HEARTH_` prefix with `__` between nested keys:

```bash
HEARTH_LLM__OPENROUTER_API_KEY=sk-...   # the API key (in .env)
HEARTH_LOGGING__LEVEL=DEBUG             # any config field
```

Config sections (as in the active `config.yaml`):

| Section | What it controls |
| --- | --- |
| `llm` | Named backends (`local`, `remote`), `tiers` (which backend serves `default` vs `tool`), `timeout`, `max_retries` |
| `veneer` | `host` / `port` of the localhost control surface (default `127.0.0.1:8765`) |
| `tool` | Wikipedia lookup — language, endpoint, result count, char cap, timeout |
| `agent` | Orchestrator limits — `max_tool_rounds`, `turn_timeout_s`, `tool_mode`, consult rounds/timeout |
| `persona` | Vesta's `system_prompt` and the `brain_guard_prompt` for consult requests |
| `conversation` | `max_history_turns` kept in-session |
| `storage` | `db_path` for the sqlite event log |
| `logging` | Rotating file handler + per-session transcript settings |

The two switches you'll most likely touch: **`llm.tiers.tool: local|remote`** (run
lookups locally or via OpenRouter) and **`llm.backends.*.model`** (swap models).

## Dev Setup

```bash
pip install -e '.[dev]'

pytest                              # asyncio_mode=auto — async tests need no decorator
pytest tests/test_e2e_veneer.py     # hermetic end-to-end proof of the spine
ruff check .                        # line-length 100
```

`tests/test_e2e_veneer.py` is the hermetic e2e; `MANUAL_SMOKE.md` is the manual
check against real Ollama/OpenRouter/Wikipedia.

**Build / release** — `make release` runs `packaging/build.sh` to produce a
single-file binary per architecture (no cross-compile; run once per target arch).

This project is developed through **fledge** (a bird/nest-themed spec-driven
process — epics are `PLM-xxx`, work units `FTHR-xxx` with numbered acceptance
criteria). The wake-word training pipeline is entirely separate — see
**[`training/README.md`](training/README.md)**; it runs in its own
`training/.venv-train` and must never share the runtime venv.

## FAQ / Good to know

**Why do I need both Ollama and an OpenRouter key?**
Two tiers: Ollama runs Vesta locally; OpenRouter serves the `consult_brain`
lookups. To run fully local (no key), set `llm.tiers.tool: local` in `config.yaml`.

**Is this a voice assistant?**
Not yet. Today it's a text spine you type at. Wake word (**Calcifer**), STT, and TTS
are roadmap; `training/` and `models/wake/` are the wake-word groundwork.

**How do I talk to it?**
Start the daemon with `hearth run`, then run `python -m hearth.veneer.client`
against it.

**Where's my data?**
The sqlite event log (`hearth.db`) and `logs/` (rotating logs plus per-session
transcripts under `logs/transcripts`).

**What hardware is this for?**
The eventual voice build targets a Raspberry Pi 5, which is why device ids, model
paths, and thresholds are all config-driven. The text spine runs anywhere with
Python 3.12 and Ollama.

**Something's broken — is it a bug or my environment?**
`MANUAL_SMOKE.md` has a section on telling missing-credentials/network issues apart
from real spine bugs.
