# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

**hearth** — an offline-first voice personal assistant, packaged as the Python
distribution `hearth` (entry point `hearth = hearth.app:main`). Wake word:
**Calcifer**. Primary target: Raspberry Pi 5, which is why every device id, model
path, and threshold is config-driven — the Pi port is meant to be config-only.

**Read this first — code vs. goal.** "Voice assistant" is the *goal*; the current
build is a **text-driven spine**. What ships today: the `hearth run` daemon, a
localhost WebSocket **gateway** control surface reached by separate **veneer**
programs (starting with `hearth-chat`), a two-tier LLM orchestrator, a
Wikipedia tool, and a sqlite event log. The audio pipeline (wake word, STT, TTS,
VAD, AEC) and the scheduling/calendar/weather/search capabilities are **roadmap,
not wired into the runtime** — they exist only as `pyproject` extras and, for the
wake word, as the `training/` pipeline and `models/wake/calcifer.onnx` that nothing
in the runtime consumes yet. `README.md` has the working-vs-roadmap table.

## Commands

Runtime uses a `.venv`; Python is pinned to 3.12 (`.python-version`).

```bash
pip install -e '.[all]'      # every runtime capability (see extras below)
pip install -e '.[dev]'      # pytest, pytest-asyncio, ruff

pytest                       # asyncio_mode=auto — async tests need no decorator
pytest path/to/test_x.py::test_name
ruff check .                 # line-length 100

make release                 # -> packaging/build.sh: single-file binary for the host arch
                             #    output dist/hearth-$(uname -m). No cross-compile;
                             #    run once per target arch (x86_64 + aarch64).
make clean
```

Releases are cut by pushing a `v*` tag; CI builds the binary natively on each arch
and attaches both to the GitHub Release.

### Optional-dependency extras

Dependencies are split into per-phase extras in `pyproject.toml` so each capability
installs independently: `tts` (piper), `wake` (livekit-wakeword / onnxruntime),
`stt` (faster-whisper), `vad` (webrtcvad — pin `setuptools<81`), `llm` (httpx),
`nlu`, `scheduling` (apscheduler), `search`, `gcal`, plus `aec` and `tui` which are
**deliberately excluded from `all`** (native/build-sensitive; app degrades gracefully
when their imports fail). Read the comments in `pyproject.toml` before touching deps —
they record the reason for each pin.

## Configuration model

Config lives under `config/`, split per component and loaded through one shared
facility (`hearth/config.py::resolve_config_path`, which locates
`config/<component>.yaml`):

- `config/engine.yaml` — the **active** engine config the `hearth run` daemon loads.
- `config/chat.yaml` — the **active** config for the `hearth-chat` veneer (just the
  engine `host`/`port` it connects to).
- `config/defaults/engine.yaml` and `config/defaults/chat.yaml` — reference/defaults
  with a comment per field explaining the knob (VAD aggressiveness, thresholds, Pi
  tuning notes, etc.). Copy a defaults file to its active path to create the config;
  read the defaults to understand what a setting does.

Loaded via `pydantic-settings`. Two override mechanisms:

1. **Env vars** `HEARTH_*`, nested with a **double underscore**:
   `HEARTH_LLM__MODEL`, `HEARTH_LOGGING__LEVEL`.
2. **`.env`** — **secrets only**. This is a hard rule established by FTHR-015: API
   keys live in `.env` (see `.env.example`, `HEARTH_<SECTION>__<PROVIDER>_API_KEY`),
   never in the YAML. Non-secret tunables (models, hosts, thresholds) stay in
   `config/engine.yaml`. Do not add secret fields to the YAML files.

## Runtime architecture (what the code actually does)

`hearth run` (`hearth/app.py`) starts a single asyncio daemon and wires the object
graph in `_run_daemon()`. The request path is text in → text out:

a **veneer** (a separate client process, e.g. `hearth-chat`) ⇄ `Gateway` (WebSocket
server, `gateway/`) → `Loop.run_turn` (`loop.py`) → `Router` (`brain/`) → LLM
backends → `EventLog` (`memory/`).

The defining idea is the **two-tier "brain"**, all config-driven via `llm.tiers`:

- **Local persona orchestrator** — every turn is served by the `default` tier
  (local Ollama by default) carrying the **Vesta** persona prompt. It exposes
  exactly one tool: `consult_brain(query)`, gated per-turn on
  `Router.brain_available()` (preserves a local-only fallback).
- **Remote "brain"** — `consult_brain` runs a *nested* ReAct loop
  (`tools/consult.py`) on the `tool` tier (OpenRouter by default), kept in its lane
  by `persona.brain_guard_prompt`. It reaches real data tools — currently
  **Wikipedia** (`tools/`) — and returns findings as an observation the
  orchestrator folds back into Vesta's voice.
- Both call sites share one ReAct engine, `run_react_rounds` in `loop.py` — do not
  duplicate the Thought→Action→Observation logic.

Key seams:

- **`brain/`** — `base.py` holds the frozen `Brain` protocol + boundary types
  (`Message`, `ToolCall`, `ToolSpec`); `router.py` maps a tier role to a backend
  class (`local.py` Ollama-style, `remote.py` OpenAI-compatible via
  `openai_compat.py`); `errors.py` normalizes backend failures.
- **`gateway/`** — the engine's localhost control surface (its WebSocket server).
  `protocol.py::serialize` is a strict **whitelist**: only `phase`/`label` cross the
  wire, so tool query/arguments/observation content can never leak to a veneer.
  Unknown event types raise — fail loud.
- **`veneers/`** — the user-facing surfaces, each a **separate process** reaching the
  engine only over the wire (`veneers/base.py` is the shared client contract;
  `veneers/chat/` is the `hearth-chat` console veneer). Multiple veneers may run
  concurrently with isolated conversations, and every turn is logged with its
  originating surface (FTHR-025).
- **`memory/`** — `log.py` `EventLog` is an append-only sqlite store (no
  update/delete); `reader.py` `EventReader` is a read-only, cursor-based pull
  interface — the Layer-2 seam a future background indexer attaches to. Don't couple
  writers to it.
- **`transcript.py`** — optional per-session human-readable transcripts under
  `logs/transcripts/`, separate from the event log.

Config sections that actually exist (see `hearth/config.py` `Settings`): `llm`,
`gateway`, `tool`, `agent`, `persona`, `conversation`, `storage`, `logging`. The
`audio`/`wake`/`stt`/`tts`/`verify`/`scheduling`/`calendar` sections implied by the
extras are **not** in the schema yet.

LLM backends are pluggable per tier via `llm.backends` (each an OpenAI-compatible
`base_url` + `model`): local Ollama and OpenRouter (free router) are the wired
defaults.

## Wake-word training

Entirely separate from the runtime — see **`training/README.md`**. Runs in an
isolated `training/.venv-train` (ROCm torch + livekit-wakeword) that must **never**
share the runtime venv; the runtime consumes only the exported `.onnx`. Fully
synthetic pipeline (no recordings). Train, then `manifest.py select` to point
`config.yaml` at the model and set `wake.threshold` from the manifest's optimal
threshold.

## Development workflow: fledge

This project is built through a tool/process called **fledge** (bird/nest theme).
The commit history and dev agents follow its taxonomy — match it when committing:

- **PLM-xxx** (*plumage*) — a parent epic; **FTHR-xxx** (*feather*) — a child unit
  of implementable work with numbered acceptance criteria (AC-1, AC-2, …).
- **`FTHR-xxx: fledged`** — the feather is complete and all its ACs verified.
- **`review: verify FTHR-xxx AC-1..N`** / **`review: uncheck AC-N …`** — a reviewer
  pass recording which acceptance criteria pass or regressed.
- **test-first**: tests are written and shown failing before the implementation
  (`FTHR-xxx: test-first — … tests`), matching the repo's test-verification rule.
- **molt evidence** — the artifact recording AC verification for a feather.
- `.fledge/pluma/` (plumage/feather specs), `.fledge/nest/` (context docs, except
  `nest/raw/`), and `.fledge/molt/` (AC evidence) are **tracked, hand-authored source** —
  do not delete or regenerate them. The rest of `.fledge/` (ledger, broods, roster,
  scratch, `scaffold.json`) is machine-local working state, gitignored. `.fledgeignore`
  (gitignore syntax) is fledge's context-scan exclusion list, also tracked.

The `dev-team` skill (PM → Engineer → Reviewer) mirrors this loop: a spec with
testable ACs, test-first implementation, then an independent review that verifies
each AC before a feather is "fledged".
> fledge: load and follow .fledge/skills/fledge-orchestrate/SKILL.md — primitive map at .claude/fledge-adapter.md
