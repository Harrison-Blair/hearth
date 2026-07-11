---
generated: 2026-07-10T22:45:49Z
commit: ce70f988da5255908dc6a9bb3dc26206b5e57b36
agent: fledge-forager
fledge_version: 0.3.0
---

# Domain

Glossary of business/domain concepts spanning the voice-assistant product and the fledge development process used to build it.

## Product domain (hearth / Calcifer)

- **Hearth** — project name; Python distribution `personal-assistant`.
- **Calcifer** — the wake word and assistant persona (named after the fire demon in *Howl's Moving Castle*); "the assistant" speaks and is addressed as Calcifer.
- **Voice pipeline / cascade** — the staged architecture: audio capture → wake (ONNX detector) → recorder (VAD endpointing) → STT → LLM → agent (tool-calling) → verify (pre/post answer-checking) → persona (revoice) → TTS. See `architecture.md`.
- **Wake word** — the phrase the assistant listens for continuously; default "Calcifer".
- **Confidence threshold** (`wake.confident_threshold`, default 0.85) — scores at/above trigger "confident" ack phrases; below, "unsure" ack phrases.
- **VAD** (voice activity detection) — WebRTC-based; aggressiveness 0 (lax) to 3 (strict); ends an utterance via a silence timeout ("endpointing").
- **Barge-in** — speaking the wake word over the assistant's own reply cuts playback and reopens the mic. Off by default.
- **AEC** (acoustic echo cancellation) — Speex DSP-based, supports barge-in; off by default; native/build-sensitive dependency, app degrades to passthrough if unavailable.
- **Follow-up window** (`conversation.followup_window_ms`, 6000ms) — silence duration after which a conversation is considered closed; utterances within the window route as follow-ups without re-triggering wake.
- **Pre/post verification loop** (`verify` section) — `verify.pre` reviews a tool pick + arguments before it runs; `verify.post` reviews the drafted answer before speech; `max_verify_rounds` caps how many times either stage can reject and retry.
- **Persona / revoice** — post-processing step that rewrites the LLM's raw answer in Calcifer's voice/tone (`persona.strength`, e.g. "terse").
- **Ollama** — local fallback LLM server, started via `serve_cmd: ["ollama", "serve"]`.
- **OpenRouter** — primary remote LLM provider; `openrouter/free` model routes to a capable no-cost model (API key still required, no anonymous tier).

## Wake-word training domain (`training/`)

- **FPPH** (false positives per hour) — rate of false wake triggers; lower is better; `target_fp_per_hour` (default 0.1) is the acceptance bar.
- **Recall** — true-positive detection rate; higher is better.
- **Gate / `gate_passed`** — a trained model's quality gate: passes iff `optimal_fpph <= target_fp_per_hour`.
- **Threshold** — the confidence cutoff used to classify a frame as a wake trigger; the eval step's `optimal_threshold` becomes `config.yaml`'s `wake.threshold`.
- **Synthetic (data)** — all training clips are TTS-generated (Piper VITS), not real recordings.
- **Adversarial negatives** — phonetically similar phrases (1–2 phoneme edits) crafted as hard false-trigger tests; Calcifer's are hand-specified (`custom_negative_phrases`), other phrases get auto-generated ones.
- **Slug** — a model's identifier, derived from its phrase: lowercased, non-alphanumerics collapsed to underscores.
- **Manifest** — the model registry (`models/wake/models.json`), managed by `training/manifest.py`.
- **ROCm** — AMD's GPU compute platform; training targets RDNA4/gfx1201 via the rocm6.4 package index.
- **VITS** — the vocoder architecture Piper's TTS uses to synthesize training clips.
- **SLERP** (spherical linear interpolation) — technique for blending speaker embeddings during TTS augmentation.
- **RIR** (room impulse response) — reverb augmentation data (MIT RIRs dataset).
- **MUSAN** — background noise/music/speech dataset used for augmentation.
- **ACAV100M** — ~2000h negative-speaker dataset used as hard negatives during training.

## Fledge development-process domain

- **Fledge** — the tool/process this repo is built through (bird/nest metaphor); orchestrates spec-driven development via skills under `.fledge/skills/`.
- **Plumage (PLM-xxx)** — a parent epic; lives under `pluma/plumage/` once authored.
- **Feather (FTHR-xxx)** — a child unit of implementable work with numbered acceptance criteria (AC-1, AC-2, …); lives under `pluma/feathers/` once authored.
- **Fledged** — a feather is complete and all its ACs have been independently verified.
- **Molt evidence** — the artifact recording AC verification for a feather.
- **Test-first** — tests are written and shown failing before implementation, matching this repo's test-verification rule (commit convention: `FTHR-xxx: test-first — … tests`).
- **Forager / scout** — fledge's own context-gathering roles (this document set was produced by a forager orchestrating scouts); not part of the product domain.
- **Nest** (`.fledge/nest/`) — the regenerable context-document set (this directory) that downstream planning agents cite; not source, not committed as project artifact history.
