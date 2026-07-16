---
generated: 2026-07-15T23:27:05Z
commit: e41ba8a73a56364e7c3bb1acf1332cadab817e45
agent: fledge-forager
fledge_version: 0.5.5
---

# Domain

Glossary of business/domain vocabulary spanning the runtime, config, and wake-word training pipeline.

## Assistant / persona

- **Calcifer** — the assistant's wake word and character persona (fire-demon voice). Referenced throughout docstrings and config; the wake-word *detector* is not yet wired into the runtime (see `architecture.md`).
- **Persona / Persona orchestrator** — the local-tier LLM run on every turn, shaped by `persona.system_prompt` (`hearth/persona.py`, `PersonaConfig`); always runs first.
- **Restyle** — a planned post-processing stage over the persona's output; currently a no-op stub (FTHR-011 placeholder).
- **Brain** — the remote-tier LLM subsystem, reachable only via `consult_brain`; research-only, kept "in its lane" by `persona.brain_guard_prompt` so it never impersonates Calcifer.
- **`consult_brain(query)`** — the single tool the orchestrator exposes; triggers a nested ReAct loop on the `tool` tier.
- **Brain-guard** — the system-prompt mechanism (`brain_guard_prompt`) that prevents the nested brain consult from leaking persona identity or scope.
- **Tier (`default` / `tool`)** — a named routing role mapped to a specific backend via `llm.tiers` config; each tier has its own model/capabilities.
- **Consult** — the nested ReAct loop triggered by `consult_brain`, running on the `tool` tier with the brain-guard prompt as its first message; only the Wikipedia tool is reachable from inside it.

## Turn / session model

- **Turn** — one user-assistant exchange, identified by `(session_id, turn_id)`; one `Loop.run_turn` pass produces one `final_answer` event.
- **Session** — the sequence of turns over one WebSocket connection; `session_id` is a `uuid4` minted per connection.
- **ReAct** — Reasoning + Acting loop (Thought → Action → Observation); the single shared engine (`run_react_rounds`) used by both the top-level orchestrator and the nested brain consult, capped by a round limit.
- **Tool activity** — a start/end event pair emitted around a tool call, surfaced to the client as `{type, turn_id, phase, label}` — never the tool's actual query/arguments/result.

## Control surface / persistence

- **Veneer** — the localhost-bound asyncio WebSocket control surface; the "front door" a client (or future audio pipeline) talks to; enforces a strict wire whitelist.
- **Whitelist protocol** — `veneer/protocol.py::serialize`'s rule that only `{type, turn_id, phase, label, text}` may cross the wire; explicitly forbidden: `{query, arguments, observation, result}`.
- **Event log** — the append-only sqlite store of every turn's lifecycle events (`user_input`, `routing_decision`, `tool_call`, `observation`, `final_answer`, `error`); no update/delete, ever.
- **Layer 2** — the not-yet-built background indexer/consumer that will attach to `EventReader`'s cursor-based read interface; `NoOpConsumer` is today's reference stub.
- **Transcript** — a separate, best-effort, human-readable per-session text log (distinct from the structured event log).

## Fledge development-process terms (repo-wide, not `hearth`-specific)

- **PLM-xxx (plumage)** — a parent epic.
- **FTHR-xxx (feather)** — a child unit of implementable work with numbered acceptance criteria (AC-1, AC-2, …); referenced directly by test files (see `testing.md`).
- **"FTHR-xxx: fledged"** — commit convention marking a feather complete with all ACs verified.
- **Molt evidence** — the artifact recording AC verification for a feather.

## Wake-word training domain (`training/`)

- **Wake word** — the short phrase that would trigger the assistant (Calcifer); training is fully decoupled from the runtime today.
- **Synthetic dataset** — no real recordings are used; all training clips are generated via Piper TTS plus MUSAN/MIT-RIR augmentation.
- **FPPH (false positives per hour)** — the operating-point metric for false triggers; `calcifer.yaml`'s default target is `0.1`.
- **Recall** — true-positive rate; livekit's threshold finder maximizes recall subject to the FPPH target.
- **Threshold** — the classifier's cutoff operating point; taken from the manifest's `optimal_threshold` after training and written into `config.yaml` via `manifest.py select`.
- **Gate / `gate_passed`** — boolean: did the trained model's optimal FPPH meet the configured target? `false` if `optimal_fpph > target_fpph`.
- **Adversarial negatives** — near-miss phonemes to the wake word (`custom_negative_phrases` in `calcifer.yaml`), used to sharpen discrimination.
- **Conv-attention** — the model architecture used (conv layers + attention head).
- **Slug** — a normalized model identifier (`manifest.py`'s `slug()`: lowercase, non-alphanumerics collapsed to underscores) used as the `models.json` key; the inverse "prettify" is lossy.

## Open Questions

- No automated test suite exists for `training/` — unclear whether livekit stage success is treated as sufficient validation, or whether informal smoke checks exist outside the repo.
- Whether the `custom_negative_phrases` defaults in `calcifer.yaml` are empirically validated for "Calcifer" specifically, or an evolving set based on observed false triggers, is not determinable from source alone.
- Exact per-`Event.type` payload schema (see `data-model.md`) is not formally documented — only inferable from call sites.
