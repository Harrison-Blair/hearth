---
generated: 2026-07-07T22:56:23Z
commit: 58fb2ba9bbeefc5db7d530261bcb3450573048fa
agent: fledge-forager
fledge_version: unknown
---

# Domain

Glossary of the project's domain vocabulary — voice-pipeline concepts, the persona/character model, the LLM/routing terms, and the fledge planning history that explains why several seams exist.

## The assistant & its character

- **Calcifer** — the assistant's persona/character (the wake word and persona are themed on the fire demon). "Penguin" and "fire demon" are also trained wake phrases.
- **Persona** — a text flavor applied to how a reply *sounds*, never to which tool runs or which facts are stated. Applied via a suffix baked into skill system prompts and via the revoicer. Two strengths: **terse** and **expansive**. Forbidden on routing/judgment prompts; permitted on spoken outputs only.
- **Revoice / Revoicer** — a live LLM call that restyles a plain (deterministic) skill reply into Calcifer's voice at the pipeline's `_speak` choke point. Bounded timeout, circuit-breaker cooldown after failure, and a **digit-preservation guard** (any digit change discards the revoice and speaks plain). PLM-003.
- **voiced flag** — `SkillResult.voiced=True` marks output already persona-flavored by an LLM (or a canned line) so it bypasses the revoice seam and avoids double-processing.
- **canned() / template registry** — a lookup of LLM-free spoken lines (error messages, offline notices, update sign-off) with 2–3 seeded-random variants per key; used when the LLM is down or a reply must be immediate. `canned()` output is always `voiced=True`.
- **Persona v2** — updated character guidance (`_CALCIFER_V2_*` blocks) that keeps replies in-character-but-brief; versioned so eval replays key on the new text.

## Voice pipeline

- **Wake word** — a spoken trigger detected during idle listening; fires a `WakeEvent`. Multiple ONNX models can load at once; phrases are *derived* from the manifest, never hard-coded.
- **VAD (Voice Activity Detection)** — per-frame speech/silence classification (webrtcvad) used to bound recording; trailing silence closes an utterance.
- **Preroll** — ~0.5s of frames held before the wake fires, recovered on capture so the command's start (clipped by detection latency) is restored.
- **Barge-in** — speaking the wake word over the assistant's own reply cuts playback and reopens the mic; enabled by the MicHub *tap* keeping detection alive during playback, gated by a raised threshold + consecutive-event debounce.
- **AEC (Acoustic Echo Cancellation)** — subtracts speaker output (far-end reference) from the mic (near-end) so the wake word stays audible during playback; optional (Speex).
- **Hallucination** — a Whisper false-positive on near-silent audio (e.g. "thank you"), filtered by an RMS gate.
- **Earcon** — a short synthetic tone/chime for terse audio feedback without speech synthesis.
- **length_scale** — Piper speaking-rate multiplier (>1 slower, <1 faster); per-call override.
- **Stand-down** — a "stop listening" state, engaged by voice/TUI for a duration or indefinitely; consumers poll `.active` on their tick, so it simply expires and a restart clears it.
- **AudioArbiter** — a single async lock serializing capture, TTS playback, and proactive announcements so they never overlap.

## LLM & routing

- **Orchestrator / tool-calling loop** — the router: exposes skill intents as tool schemas and asks the LLM to call one tool (arguments → `Intent.slots`) or answer directly. `tool_mode` native/json/auto.
- **Tool call / tool schema** — an OpenAI-style function definition per intent; the model's request to invoke a skill.
- **Skill / intent / slot** — a plug-in handler for related intents (`Skill`); an intent is a routed request category; a slot is a parsed argument. `GeneralSkill` is the always-present `default` fallback.
- **Verify loop** — optional two-stage LLM judgment: *pre* reviews the tool pick + args, *post* reviews the drafted answer; can approve/reject/rewrite. Fail-open on parse error. Bounded by `max_tool_rounds` / `max_verify_rounds`.
- **Fallback (LLM)** — a secondary provider invoked when the primary fails (transport/timeout/parse); empty responses do not trigger it.
- **LLM tier** (TUI) — health of the provider chain: **up** (primary ok), **degraded** (primary down, fallback up), **down** (both unavailable).
- **think / thinking models** — reasoning models (e.g. qwen3) whose reasoning bloats voice latency and pollutes JSON; suppressed for JSON completions (Ollama-specific flag).
- **retryable vs non-retryable** — transient failures (429/5xx/transport, malformed 200) retry with backoff; permanent config/auth errors (401/403) do not. `LLMResponseError.retryable` carries this.
- **Zen / OpenCode Zen** — the OpenAI-compatible remote LLM gateway; free model ids end in `-free`.

## Search, calendar, time

- **Routed dispatch (PLM-002)** — query-type classification (factual→Tavily, semantic→Exa) picks the AI search provider; the keyless tier (Wikipedia/DuckDuckGo) is the fallback.
- **Answer block** — Tavily's synthesized summary, embedded as the first `SearchResult` (source `"tavily"`). **Highlights** — Exa's priority excerpts, preferred over full text for a snippet.
- **Agentic search** — the WebSearchSkill's refine→search→assess loop (up to `max_rounds`) with LLM-steered queries and injection defense.
- **Speakable title** — an event/result title with TTS-hostile symbols (emoji, etc.) stripped.
- **EventBlocklist / block pattern** — substring patterns (config + voice-added + a hidden tag) that suppress calendar events from unprompted queries and the watcher.
- **Lead window / lead_minutes** — the interval `[now, now+lead_minutes]` over which the CalendarWatcher announces upcoming events.
- **Dedupe** — marking an event announced by `(event_id, start_epoch)` so it isn't re-announced (a reschedule = new start = re-announce).
- **Boot catch-up / away preamble** — the first scheduler poll after restart coalesces multiple due reminders into one "While I was away, N reminders came due" summary.
- **Reminder kind / interval** — `kind` discriminates `reminder` vs `timer` in one table; `interval` sets recurrence (None = one-shot).

## Self-update (PLM-001)

- **Restart in place** — `os.execv` re-execution of the same Python process (same PID, inherited FDs); a fresh interpreter loads the on-disk code.
- **Post-speak restart seam** — the pipeline honors `SkillResult.restart=True` only after `_speak()` completes, so the sign-off is audible before the process is replaced.
- **pdeathsig** — `PR_SET_PDEATHSIG`; ensures the TUI-supervised daemon survives (and is reaped correctly across) the re-exec.

## Wake-word training

- **FPPH (False Positives Per Hour)** — the false-wake rate; 0.1 FPPH (one spurious wake per 10h) is the target gate.
- **Recall / optimal threshold** — fraction of true wakes detected; the score cutoff livekit's `find_best_threshold` picks to maximize recall subject to target FPPH.
- **Adversarial negatives** — hard negatives (1–2 phoneme edits, e.g. "calcify" for "calcifer") to sharpen the classifier.
- **conv_attention** — livekit's hybrid CNN-attention wake architecture. **ACAV100M / MUSAN / MIT RIRs** — negative and room-augmentation datasets. **SLERP** — spherical interpolation of Piper speaker embeddings for voice diversity.
- **Slug / manifest** — normalized model name (phrase → lowercase underscores); `models.json` registry of trained models, phrases, eval metrics, and deployment paths. **Smoke run** — a tiny end-to-end pipeline check (`_smoke` suffix) before a production run.

## Fledge planning vocabulary

- **Plumage (PLM)** — a feature-level planning spec. Completed: **PLM-001** self-update/restart-in-place, **PLM-002** AI-first web search (Tavily/Exa + query routing), **PLM-003** persona-flavored revoice seam + canned templates.
- **Feather (FTHR)** — a vertical implementation slice of a plumage (FTHR-001..009, all fledged). E.g. FTHR-003 Tavily seam, FTHR-004 Exa route, FTHR-005 revoicer seam, FTHR-006 persona v2 + registry, FTHR-009 hardening invariants (spy-TTS flavor guarantee + persona-free routing).
- **fledged** — a spec whose implementation is merged and its acceptance criteria verified.
- **Spy fixtures** — test doubles (stub LLM, spy TTS, tagging revoicer) that record calls / inject marker tags to verify invariants without side effects.
- **Nest** — this `.fledge/nest/` context set. **Forager / scout** — the agents that regenerate it (a forager orchestrates per-module scouts).

## Reference-architecture terms (from `docs/`)

- **ReAct** — interleaved Thought→Action→Observation single-agent reasoning pattern (the default local agentic style).
- **Tool-calling reliability cliff** — models <7–9B params drop sharply below ~66% BFCL; Qwen3/3.5 are the most reliable local tool-callers.
- **Hybrid RAG** — vector+BM25 retrieval reranked by a cross-encoder to top-5.
- **Deterministic fast-path** — routine commands routed to an intent parser before the LLM.
- **Wyoming protocol** — Home Assistant's abstraction for swappable local voice services.
- **MCP (Model Context Protocol)** — emerging tool-exposure standard; dominant risk is prompt injection (OWASP LLM Top-10 #1).
