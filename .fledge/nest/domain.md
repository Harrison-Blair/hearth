---
generated: 2026-07-08T00:34:07Z
commit: 0a67e65dc3d33b2e9c911f1296eef515124fa678
agent: fledge-forager
fledge_version: unknown
---

# Domain Glossary

Vocabulary used across the codebase, specs, and this documentation. Grouped by area.

## Pipeline & routing
- **Wake word** — the trigger phrase ("Calcifer"), detected by an on-device ONNX classifier. A score above `wake.threshold` fires a turn; above `confident_threshold` gets a confident ack, below gets an "unsure" ack.
- **Voice pipeline** — the single async loop (`VoicePipeline`): wake → record (VAD) → transcribe (STT) → route → skill → speak (TTS).
- **VAD (Voice Activity Detection)** — WebRTC-based end-of-speech detection in the recorder; trailing-silence threshold closes the utterance.
- **STT / TTS** — speech-to-text (faster-whisper) / text-to-speech (Piper).
- **Preroll** — ~0.5 s of audio kept before wake detection, recovered if a command was clipped.
- **Orchestrator** — the LLM tool-calling router; picks a skill tool (or answers directly) and executes it, with optional verify gates.
- **Skill** — a plug-in capability (one `Skill` subclass) declaring `name` + `intents`; the unit of routable behavior.
- **Intent** — a routed direction; `type` is the skill/intent name, `slots` are the tool-call arguments.
- **Tool / tool schema** — a skill intent exposed to the LLM as an OpenAI-style function; the model calls it, its arguments populate `Intent.slots`.
- **Tool-repeat cap** — a guard (`_TOOL_REPEAT_CAP=2`) that breaks infinite loops of the same tool producing no speech.
- **Default / fallback skill** — the `default=True` skill (`GeneralSkill`); reached on LLM/JSON failure, unknown tool, timeout, or when the model answers directly.
- **Verify loop** — optional pre-tool and post-answer LLM gates that approve / rewrite / reject; fails open (a `None` verdict approves).
- **Verdict** — the verify decision record (approve/rewrite/reject + optional rewritten tool/args/speech).
- **Conversation / follow-up** — multi-turn state; after a reply the assistant may keep listening for a follow-up within `followup_window_ms` without a new wake word.
- **Barge-in** — speaking the wake word over the assistant's reply; cuts playback and reopens the mic (needs AEC; off by default).

## Speech & persona
- **Persona (Calcifer)** — the fire-demon voice character applied only to spoken output, never to routing/verify/tool-decision prompts. Strength is "terse" or "expansive".
- **Revoicer / revoice** — a live LLM restyle pass at the speak choke point that rewrites a plain reply in the persona's voice (one call, digit-preserving, circuit-breaker on failure).
- **Voiced flag** — `SkillResult.voiced`; `True` marks a reply already persona-flavored so the revoicer is skipped.
- **Canned line / `canned()`** — an LLM-free, in-character spoken string (errors, offline, sign-offs); rotated variants, plain string when persona is off.
- **Earcon** — a short non-speech audio cue (mic-open chime, end tone, check-in chirp), synthesized, not recorded.
- **Stand-down** — a shared "stop listening" state ("stand down for 5 minutes"); pipeline and proactive tasks poll `.active`; expires on timer or daemon restart.

## LLM provider layer (PLM-004)
- **Provider** — a concrete `LLMProvider`: `OllamaProvider` (local), `OpenAICompatibleProvider` (gateway), `FallbackLLMProvider` (primary+fallback wrapper).
- **Gateway** — an OpenAI-compatible HTTP endpoint (`/chat/completions`, bearer auth, tools + `response_format`).
- **GATEWAYS table** — the vendor-neutral map from a config provider name to its base URL + extra headers; add an entry to support a new gateway with no new per-vendor code. Current entries: `opencode-zen`, `openrouter`.
- **OpenRouter** — the current primary gateway; one API key fronts many vendors; the `openrouter/free` meta-model routes each request to a capable free model (a key is still required; free models rate-limit and rotate).
- **OpenCode Zen** — an alternate gateway (`opencode-zen`), preserved in the table and as a commented config profile.
- **OpenAI-compatible** — the wire protocol every gateway speaks; the generic provider replaced the removed vendor-specific `opencode_zen_provider.py`.
- **Fallback provider** — a primary LLM with a secondary (usually local Ollama) used only when the primary raises.
- **Health check** — a provider readiness probe (Ollama: model pulled; gateway: `/models` answers); a failure logs a warning and the daemon degrades rather than crashing.
- **Transient / retryable** — a failure eligible for retry (429, 5xx, transport error, malformed 200); 4xx-auth (400/401/403) is never retried.
- **Vendor-neutral diagnostics** — boot endpoint logging and unhealthy warnings driven by `GATEWAYS[provider]`, not hard-coded vendor checks.

## Config & secrets
- **Config as single source of truth** — every tunable is a typed `*Config` field; `config.yaml` → typed models; nothing hard-coded.
- **Env override** — `ASSISTANT_<SECTION>__<FIELD>` (`__` = nesting); precedence init args > env > `config.yaml`.
- **Secret vs configuration** — API keys/credentials (secrets) live in the environment (`.env`, delivered by the TUI), never in committed YAML; non-secret tunables live in `config.yaml`.
- **Per-provider secret** — a keyed provider's credential stored as its own config field and passed into the provider constructor (`tavily_api_key`, `exa_api_key`, and `llm.api_key`).
- **Override** (TUI) — a session-only `ASSISTANT_*` env var applied to a daemon (re)start without rewriting `config.yaml`.

## Capabilities
- **SearchProvider** — the web-search ABC; keyless (ddgs, Wikipedia) and keyed (Tavily, Exa) backends plus a `MultiSearch` fan-out composite.
- **AI-first search** — keyed APIs chosen by query type: factual → Tavily, semantic → Exa; keyless tier as fallback.
- **Query-type routing** — the LLM classifies a query (factual vs semantic) to pick the search backend.
- **Synthesized answer** — an LLM-generated summary from Tavily carried as a special `SearchResult`.
- **Blocklist** — calendar-title patterns (voice-added, config, or `[hidden]` description tag) that suppress unprompted event mentions.
- **Speakable title** — an event title with TTS-hostile symbols/emoji stripped.
- **Reminder / Timer** — a timed spoken alert stored in SQLite; `kind` distinguishes them; a `label` names a timer; a non-null `interval` makes it recurring.
- **Lead window** — the `[now, now+lead_minutes]` range the calendar watcher announces within.
- **Catch-up** — a single summary announcement of reminders that came due while the assistant was offline, fired on the scheduler's first poll.
- **Deduplication** — the watcher announces each `(event_id, start_at)` once; a rescheduled event gets a new key and re-announces.

## Runtime plumbing
- **Composition root** — `app.py`, the only place concrete implementations are constructed and wired.
- **AudioArbiter** — an async lock serializing the single audio device so proactive announcements never collide with capture/playback.
- **Control channel** — the stdin line protocol from the TUI to the daemon (TEXT/LISTEN/CANCEL/STOP/SAY/RESUME/SET).
- **State feed (`@@STATE`)** — JSON lines the daemon writes to stdout describing state/transcript/reply/level; the TUI parses them for the Now screen.
- **Self-update / restart-in-place** — `os.execv` re-execs `python -m assistant.app`, same PID and fds, to load on-disk code changes without network/git/install.

## Wake training
- **Calcifer model** — the trained wake classifier `models/wake/calcifer.onnx`.
- **Manifest (`models/wake/models.json`)** — the registry of trained wake models (slug, phrase, metrics, path); phrases are also derived from filenames.
- **FPPH** — false positives per hour, the wake-model eval target (`target_fp_per_hour 0.1`).
- **Adversarial / hard negatives** — near-miss phrases (1–2 phoneme edits from "calcifer") that teach discrimination.
- **VITS / Piper** — the TTS used to synthesize training clips (no real recordings).
- **ROCm / HIP** — the AMD GPU stack used for training (RDNA4/gfx1201 needs ROCm ≥ 6.4).

## Fledge / specs
- **Plumage (PLM-NNN)** — a feature-area specification (context, functional criteria FC-N, acceptance criteria AC-N).
- **Feather (FTHR-NNN)** — an implementable slice of a plumage with its own acceptance criteria and a `depends_on` DAG.
- **Fledged** — a spec whose acceptance criteria are all checked/closed. All 4 plumages and 12 feathers are fledged; PLM-004 (+ FTHR-010/011/012) delivered the OpenAI-compatible LLM gateway.
- **Nest** — this `.fledge/nest/` context document set that downstream planning agents read.
