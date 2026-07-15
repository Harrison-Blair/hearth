---
generated: 2026-07-15T22:30:28Z
commit: a8489b1afa55662a54ba66548a2e176584a3f387
agent: fledge-forager
fledge_version: 0.5.4
---

# Domain

Glossary of business/domain concepts embodied in the codebase, spanning the runtime, the wake-word training pipeline, and the fledge development process.

## Product concepts

- **Calcifer** — the wake word, and the local persona's in-character name (root.md, hearth.md).
- **Persona** — the local LLM's in-character voice/identity layer; the top-level orchestrator always answers as Calcifer. Currently `hearth/persona.py:restyle()` is a no-op stub (revoicing not yet implemented, tracked toward FTHR-011) (hearth.md).
- **Brain** — the remote LLM subsystem, reached only via the `consult_brain` tool from the persona layer; implements the `Brain` protocol (async `complete()`) shared with the local backend (root.md, hearth.md).
- **Veneer** — the WebSocket control-surface boundary between a client and the daemon; also enforces a strict serialization whitelist so internal tool activity never leaks query/argument/result content to the client (root.md, hearth.md).
- **Tier** — a routing role for LLM backend selection: `default` (ordinary turns, always local) vs. `tool` (tool-calling/consult rounds, always remote) (root.md, hearth.md, tests.md).
- **Consult** — a nested call from the persona to the brain via the `consult_brain` tool, itself running its own ReAct loop over real data tools (root.md, hearth.md).
- **ReAct** (Reason + Act) — the Thought → Action → Observation loop implemented once in `hearth.loop.run_react_rounds()` and shared by both the top-level orchestrator and nested consult (hearth.md, tests.md).
- **Tool round** — one step of a ReAct loop: `brain.complete()` returns tool calls → dispatch → observation → `brain.complete()` again; capped at a configurable `round_cap` (hearth.md).
- **Tool activity** — the `ToolActivity(turn_id, phase, label)` start/end event pair emitted while a tool runs, the only thing that crosses the veneer wire about tool execution (hearth.md).
- **Session** — a conversation context scoped to one WebSocket connection, identified by `session_id` (`uuid4().hex`); can span multiple turns (hearth.md).
- **Turn** — one user query → assistant response cycle, identified by `turn_id`; every internal step (routing decision, tool calls, observations, final answer) is logged against it (hearth.md).
- **Event log** — the append-only SQLite record of everything that happens during a turn, keyed by `session_id`/`turn_id` (hearth.md, root.md).
- **Transcript** — a per-session, human-readable line-by-line log of user input and Calcifer's answers, distinct from the structured event log (hearth.md, root.md).
- **Spine** — informal term (root.md) for the currently-implemented text/voice orchestration core (daemon + veneer), as distinct from the not-yet-built audio front end.

## Wake-word training domain

- **Wake word / hotword** — the phrase the assistant listens for (e.g. "Calcifer"); the runtime must detect it in live audio to trigger listening (training.md).
- **Positive samples** — synthetic TTS renderings of the target wake phrase, used as training data (training.md).
- **Negative samples** — audio that must NOT trigger: background speech (ACAV100M), general noise (MUSAN), and hand-authored **adversarial negative phrases** (phonetically 1–2 edits from the wake word, e.g. "calcify", "classifier", "lucifer" for "calcifer") — trained in specifically to suppress confusable false triggers (training.md).
- **FPPH (False Positives Per Hour)** — the false-alarm-rate metric; `target_fp_per_hour` is the acceptance gate for a trained model (e.g. 0.1 = one false trigger per 10 hours) (training.md, models.md).
- **Recall** — true-positive rate at the model's chosen operating threshold (training.md, models.md).
- **Threshold** — the decision boundary chosen post-training to hit the FPPH target while maximizing recall (training.md, models.md).
- **Gate / `gate_passed`** — whether a trained model met its FPPH acceptance target; recorded per-model in `models/wake/models.json` (training.md, models.md).
- **Conv-attention** — the neural network architecture livekit-wakeword trains (configurable small/medium/large) (training.md, models.md).
- **Livekit-wakeword** — the open-source training framework driving the whole synthetic pipeline (no real recordings) (training.md, models.md).
- **SLERP** — spherical linear interpolation, used to blend TTS speaker embeddings (`slerp_weights`) for voice variation without multiple voice models (training.md).
- **Augmentation** — MIT RIR convolution (simulated rooms) + MUSAN background mixing + clip-duration variation, applied to synthetic samples for acoustic robustness (training.md).
- **Model slug** — the normalized phrase name used as the manifest key, filename stem, and config reference (`training/manifest.py:slug`) (training.md).
- **Smoke run** — a fast plumbing test of the training pipeline (200 samples, 500 steps), distinct from pytest's automated tests; appends `_smoke` to the model name (training.md).
- **Fresh / fresh-clips** — flags that discard checkpoints (`--fresh`) or the entire model working directory (`--fresh-clips`) to restart training from scratch (training.md).

## Build/release domain

- **Bundle root** (`sys._MEIPASS`) — the PyInstaller frozen-app extraction directory; `config.yaml` is placed here so `hearth.config` resolves it correctly inside the single-file binary (packaging.md).
- **Native runners** — CI builds each architecture's binary on architecture-native GitHub Actions hardware rather than cross-compiling, because PyInstaller cannot cross-compile (packaging.md, `CLAUDE.md`).
- **Smoke test** (CI sense, distinct from training's smoke run) — minimal binary invocation (`--version`, then a DEBUG-level startup truncated to 40 lines) proving all native imports resolved and no missing runtime precondition crashes immediately (packaging.md).

## Fledge development-process domain

- **Fledge** — the bird/nest-themed spec-driven development process this repo is built through (`CLAUDE.md`, root.md).
- **Plumage (PLM-xxx)** — a parent epic.
- **Feather (FTHR-xxx)** — a child, implementable unit of work with numbered acceptance criteria (AC-1, AC-2, …).
- **Fledged** — a feather is complete and all its ACs verified (commit convention: `FTHR-xxx: fledged`).
- **Molt evidence** — the artifact recording AC verification for a feather.
- **Test-first** — tests written and shown failing before implementation, matching the repo's test-verification rule (commit convention: `FTHR-xxx: test-first — … tests`).

## Open Questions

- None additional beyond those already logged in architecture.md / entry-points.md regarding unimplemented voice-pipeline stages.
