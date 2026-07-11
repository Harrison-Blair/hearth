# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

**hearth** — an offline-first voice personal assistant, packaged as the Python
distribution `personal-assistant` (entry point `assistant = assistant.app:main`).
Wake word: **Calcifer**. Primary target: Raspberry Pi 5, which is why every device
id, model path, and threshold is config-driven — the Pi port is meant to be
config-only.

### Current repo state (important)

The runtime source is **not on disk right now**. The repo is mid-restart (see
`git log`: `ce70f98 restarting (again)`). Only these are tracked:

- `config.yaml` / `default-config.yaml` — active + reference configuration
- `models/wake/calcifer.onnx` — trained wake model + `models.json`
- `training/` — wake-word training pipeline (self-contained, has its own README)
- `pyproject.toml`, `Makefile`, `.github/workflows/release.yml`, `.env.example`

`pyproject.toml`, the training README, and configs reference packages that a live
tree is expected to contain but which are **absent here**: `assistant/` (runtime),
`tui/` (Textual monitor), and `packaging/build.sh` (invoked by `make release`).
When asked to work on runtime code, confirm whether it should be (re)created rather
than assuming files exist.

## Commands

Runtime uses a `.venv`; Python is pinned to 3.12 (`.python-version`).

```bash
pip install -e '.[all]'      # every runtime capability (see extras below)
pip install -e '.[dev]'      # pytest, pytest-asyncio, ruff

pytest                       # asyncio_mode=auto — async tests need no decorator
pytest path/to/test_x.py::test_name
ruff check .                 # line-length 100

make release                 # -> packaging/build.sh: single-file binary for the host arch
                             #    output dist/assistant-$(uname -m). No cross-compile;
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

Two files, both documented inline:

- `config.yaml` — the **active** config the daemon loads.
- `default-config.yaml` — reference/defaults with a comment per field explaining the
  knob (VAD aggressiveness, thresholds, Pi tuning notes, etc.). Read this to
  understand what a setting does.

Loaded via `pydantic-settings`. Two override mechanisms:

1. **Env vars** `ASSISTANT_*`, nested with a **double underscore**:
   `ASSISTANT_LLM__MODEL`, `ASSISTANT_LOGGING__LEVEL`.
2. **`.env`** — **secrets only**. This is a hard rule established by FTHR-015: API
   keys live in `.env` (see `.env.example`, `ASSISTANT_<SECTION>__<PROVIDER>_API_KEY`),
   never in the YAML. Non-secret tunables (models, hosts, thresholds) stay in
   `config.yaml`. Do not add secret fields to the YAML files.

## Runtime architecture (from config)

A staged voice pipeline, each stage a config section:

`audio` capture → `wake` (livekit onnx detector) → `recorder` (WebRTC VAD
endpointing) → `stt` (faster-whisper) → `llm` → `agent` (tool-calling rounds) →
`verify` (pre/post answer-checking loop) → `persona` (revoice) → `tts` (piper).

Cross-cutting: `conversation` (follow-up window, history), `scheduling`
(apscheduler), `web_search`, `weather`, `calendar` (Google service-account, async
httpx), `storage` (sqlite `assistant.db`), `aec`/`barge_in` (echo cancellation,
off by default), `logging` (rotating file logs under `logs/`).

LLM provider is pluggable: `ollama` (local), `openrouter`, `opencode_zen`, with a
`fallback` provider/model. OpenRouter's free router is the current primary.

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
- `.fledge/` and `.fledgeignore` (gitignore syntax) are fledge's working state /
  context-scan exclusions; both are ignored/regenerable, not source.

The `dev-team` skill (PM → Engineer → Reviewer) mirrors this loop: a spec with
testable ACs, test-first implementation, then an independent review that verifies
each AC before a feather is "fledged".
> fledge: load and follow .fledge/skills/fledge-orchestrate/SKILL.md — primitive map at .claude/fledge-adapter.md
