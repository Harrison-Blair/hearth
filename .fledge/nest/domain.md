---
generated: 2026-07-17T06:36:02Z
commit: 2cf763f017cef0f330f2fb0df7157c947be1113a
agent: fledge-forager
fledge_version: 0.6.7
---

# Domain

Glossary of business/domain vocabulary hearth's code embodies, reconciled across scout reports (raw reports disagreed on persona naming — see the note below).

## Core architectural terms

- **Two-tier brain** — the defining architectural pattern: a local persona orchestrator (tier `"default"`) + a remote research "brain" (tier `"tool"`), fully config-driven; supports fully-local, fully-remote, or split deployments.
- **Persona orchestrator** — the local LLM tier that answers every turn, carrying the persona system prompt. Exposes exactly one tool, `consult_brain(query)`.
- **Brain** — (a) informally, the whole LLM routing subsystem (`hearth/brain/`); (b) specifically, the remote research tier reached via `consult_brain`, kept in its lane by `persona.brain_guard_prompt`.
- **Tier** — a role (`"default"` or `"tool"`) bound to a named backend via `llm.tiers`; fully config-driven, resolved by `Router.select()`.
- **Backend** — a concrete LLM endpoint implementation of the `Brain` protocol: `LocalBackend` (Ollama-style) or `RemoteBackend` (OpenAI-compatible remote, e.g. OpenRouter).
- **ReAct** — Reasoning + Action: the Thought→Action→Observation loop. Implemented once, shared, in `run_react_rounds()` (`hearth/loop.py`), used both by the top-level orchestrator turn and by the nested `BrainConsult` invocation.
- **consult_brain(query)** — the single tool the persona orchestrator exposes; triggers a nested ReAct loop on the tool tier; gated per-turn by `Router.brain_available()`.
- **BrainConsult** — the class (`hearth/tools/consult.py`) implementing `consult_brain`; runs nested `run_react_rounds()` over the tool tier with the `ToolRegistry` bound; degrades to a plain-text observation on `BrainError` or timeout, never raises out to the caller.
- **Veneer** — the localhost WebSocket control surface (`hearth/veneer/`) separating the core engine from external clients; serializes only `phase`/`label` (plus `type`/`turn_id`) onto the wire. Slated to be renamed **`chat`** in an upcoming plumage, alongside the introduction of a new **audio veneer** (wake word, VAD, STT, TTS) — see `architecture.md` for the reference list of what the rename touches.
- **Turn** — one user-query→answer cycle; identified by `turn_id` (UUID hex).
- **Session** — one persistent client connection; identified by `session_id` (UUID hex); may carry multiple turns sequentially.
- **Tool activity** — a `phase` (start/end) + `label` (e.g. "search") event emitted mid-turn to the client; tool internals (query, arguments, observation, result) never cross this boundary.
- **Event log** — the append-only sqlite store (`hearth.db` by default) recording turns, routing decisions, tool calls, and observations; read back to reconstruct conversation history.
- **Layer2 / Layer-2** — the planned background-consumer/indexer layer that reads from the event log via the read-only, cursor-based `EventReader` seam; currently only a `Protocol` + no-op stub (`Layer2Consumer`, `NoOpConsumer`), no scheduler wired.
- **Cursor** — an event `id` used for Layer-2 pagination; `EventReader.read_since(cursor)` returns events with `id > cursor`; `0` means start of log.
- **Guard prompt** — `persona.brain_guard_prompt`, injected as the first system message into every nested `consult_brain` request, keeping the remote tier "in its lane" (FTHR-010).
- **Transcript** — a per-session, human-readable log file (`logs/transcripts/<session_id>.txt`) separate from the event log; best-effort, write failures are swallowed.
- **Finish reason** — the LLM's stated reason for stopping generation (`"stop"`, `"tool_calls"`, `"max_tokens"`, etc.), carried on `BrainResult`.
- **Cost tier** — categorization of a backend's cost (`"free"`, `"cheap"`, `"expensive"`), part of `Capabilities`.
- **Tool mode** — `agent.tool_mode` config field controlling how tool-calling is expressed to the LLM (`native | json | auto`).

## Persona naming — reconciled

Scout reports disagreed here: `root.md` and some of `hearth-core.md` name the persona **"Vesta"**; `hearth-core.md`'s own domain section also flags "persona.py comment mentions 'Vesta' but code generic" — i.e. the *code* does not hardcode a persona name, "Vesta" appears only in config/prompt text and tests (`llm_config()`/model name `qwen3:14b`, persona system-prompt content). **Calcifer** is named as the project's **wake word** only by root `CLAUDE.md` ("Wake word: Calcifer") — it appears nowhere in the runtime, config, or training artifacts: the persona system prompt says "You are Vesta", `training/phrases.txt` targets Vesta/Prometheus/Ignis, and the only committed wake model is `models/wake/vesta.onnx`. Do not conflate the two: Calcifer is what the assistant listens for; the persona's spoken name (if any) is a config/prompt-level detail, currently defaulting toward "Vesta" in this repo's default config and test fixtures, not a hardcoded identity in `hearth-core`'s code.

## Wake-word training domain (`training/`)

- **Wake word / wake phrase** — the short utterance the assistant listens for. Current active phrases (`training/phrases.txt`): Vesta, Prometheus, Ignis. `CLAUDE.md` still names Calcifer as the wake word, but no calcifer artifact or training config exists — Vesta is the trained/committed target (see Open Questions).
- **Fully synthetic (training)** — no real audio recordings; positive clips synthesized via Piper VITS, adversarial negatives are also TTS-generated, background negatives drawn from the ACAV100M public speech corpus.
- **Adversarial negative phrases** — phonetically close false-positive candidates (1–2 phoneme edits from the target wake word, e.g. "vespa"/"vesta's" for Vesta), curated per phrase or auto-generated by `train_batch.py`.
- **FPPH (False Positives Per Hour)** — the operating-point metric; a trained model's threshold is tuned to minimize false-positive rate while hitting a target recall.
- **Gate** — pass/fail on whether a model's optimal FPPH ≤ `target_fp_per_hour` (production configs use 0.1); recorded in the manifest as `gate_passed`.
- **Manifest** — the model registry (`models/wake/models.json`), indexed by slug, tracking phrase, path, recall, FPPH, threshold, gate status, and training timestamp per model.
- **Smoke run** — a tiny end-to-end training run (~200 samples, 500 steps, `_smoke` model-name suffix) that proves the pipeline works before committing to a full ~25k-sample production run.
- **Sweep** — a cost-reduced training run (e.g. 5,000 samples / 20,000 steps) used to rank candidate wake phrases before a full production run.

## Development-process domain (fledge)

- **PLM-xxx (plumage)** — a parent epic.
- **FTHR-xxx (feather)** — a child unit of implementable work with numbered acceptance criteria (AC-1, AC-2, …).
- **Fledged** — a feather is complete and all its acceptance criteria verified (`FTHR-xxx: fledged`).
- **Molt evidence** — the artifact recording acceptance-criteria verification for a feather.

## Open Questions

- Is "Vesta" the current/canonical persona name, and is Calcifer purely the wake word, or are Vesta/Prometheus/Ignis competing wake-word candidates that predate settling on Calcifer? The repo's own naming is inconsistent across config, tests, and training artifacts — worth clarifying before the audio-veneer plumage locks in terminology.
- How does `training/`'s output eventually integrate with the runtime — is there a planned domain concept (e.g. "active wake model") that `hearth/config.py` will need to represent?
