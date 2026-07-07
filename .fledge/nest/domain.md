---
generated: 2026-07-07T07:06:00Z
commit: 02f839d7a116780b02510c2d5b339c23c64a51f5
agent: fledge-forager
fledge_version: unknown
---

# Domain Glossary

Business/domain vocabulary used throughout the codebase, with brief definitions and where each concept lives.

## Voice pipeline
- **Wake word** — spoken trigger phrase (e.g. "Calcifer", "Hey Penguin") detected by the ONNX classifier; fires when the score clears `threshold` for `trigger_frames` consecutive frames.
- **Wake phrase** — human-readable phrase derived from a trained model's filename/manifest, never hand-maintained (`wake/registry.py`).
- **Confident threshold** — a higher wake score cutoff (`confident_threshold`) that selects enthusiastic `ack_phrases` vs. uncertain `unsure_ack_phrases`.
- **VAD (Voice Activity Detection)** — WebRTC classifier marking speech vs. silence at 10/20/30 ms; bounds an utterance (`silence_ms`, `start_timeout_ms`, `min_speech_ms`, `preroll_frames`).
- **Preroll** — ~0.5 s of audio kept before the wake event so a command clipped by detection latency is recovered.
- **Utterance / transcript** — the user's spoken (or typed) input, and its STT-decoded text.
- **Hallucination phrase** — a known Whisper false-positive on silence (e.g. "thank you", a YouTube outro); dropped when capture RMS is below `hallucination_max_rms`.
- **Earcon** — a short synthesized non-speech cue (chime, descending, checkin, no-speech) signaling a state transition (`audio/earcon.py`).
- **Barge-in** — speaking the wake word over the assistant's reply, cutting playback and reopening the mic; needs AEC + the mic tap.
- **AEC (Acoustic Echo Cancellation)** — subtracts speaker output (far-end reference) from the mic signal (near-end) so playback doesn't self-trigger; optional (`speexdsp`), passthrough if absent.
- **Far-end / near-end** — playback audio fed to the canceller vs. microphone audio possibly contaminated by echo.
- **Tap / drain** — a per-frame synchronous callback on the mic (enables barge-in wake scoring during playback) / discarding buffered frames so an earcon/TTS echo isn't transcribed.

## Conversation & control
- **Follow-up / conversation mode** — turns after the first wake without re-triggering the wake word, within `followup_window_ms`.
- **Decision loop** — an LLM judgment after a reply on whether to end, check-in (confirm), or keep listening.
- **Stand-down** — a timed or indefinite "stop listening" state (`StandDown`) that suppresses wake detection, reminders, and calendar announcements; polled cooperatively, cleared by TUI/timeout/restart.
- **Barge / announcement barge** — cutting a proactive reminder/calendar announcement with the wake word.
- **Control channel** — the daemon's stdin command interface from the TUI: TEXT, SET, SAY, LISTEN, CANCEL, STOP, RESUME.
- **Audio arbiter** — the single lock serializing capture, playback, and announcements so they never collide.

## Routing & reasoning
- **Skill** — a plug-in handler for one or more intents (weather, reminder, web_search, …); a `Skill` subclass.
- **Intent** — a semantic action routed to a skill; its `type` equals the tool name.
- **Slot** — an extracted argument to an intent (e.g. `location`, `duration`, `query`).
- **Tool call / tool-calling** — the LLM invoking a skill via a structured `ToolCall` (name + JSON arguments); arguments populate `Intent.slots`.
- **Tool schema** — an OpenAI-style function definition exposed to the LLM (`SkillRegistry.tool_schemas()`).
- **Orchestrator** — the tool-calling routing loop; native→JSON→general fallback.
- **Direct answer** — the LLM answering with no tool call; either spoken verbatim or delegated to `GeneralSkill` for a persona re-voice.
- **Default skill** — the fallback (`GeneralSkill`, `default=True`) used on no tool match, LLM failure, or timeout; exposes no tool.
- **Tool-calling cliff** — (design lore) below ~7–9B params, tool-call accuracy drops sharply; motivates JSON fallback + small-model prompt tightening.
- **Verification loop / Verdict** — an optional LLM re-review of the tool pick (pre) and drafted answer (post), returning approve/rewrite/reject; fails open, speaks filler only on reject, keeps the best draft on timeout.
- **Persona** — the "Calcifer" (sardonic fire-demon) tone layer appended only to spoken outputs, never to routing/verdict fields.
- **Health check / degradation / tier** — a provider readiness probe; on failure the system logs a warning and uses a fallback. The TUI shows an LLM tier: **up** (all healthy), **degraded** (some healthy), **down** (all failing).

## Web search (focus area)
- **SearchProvider** — the ABC any web-search backend implements (`search`, `health`, `aclose`).
- **SearchResult** — one hit: title, snippet, source (bare domain or label), url.
- **Keyless vs. keyed provider** — no-API-key backends (DuckDuckGo scraper, Wikipedia) vs. keyed ones (Tavily/Exa/Brave — the planned AI-first additions).
- **AI-first search** — a search API designed for LLM consumption (returns clean, synthesizable snippets), the direction the capability is being extended toward.
- **Fan-out** — `MultiSearch` querying all providers concurrently rather than in sequence.
- **Round-robin merge** — interleaving results by rank (top hit from each provider first) to preserve provider diversity.
- **Deduplication** — dropping repeat results by normalized URL (or `source:title` when URL is empty).
- **Agentic search loop** — the `WebSearchSkill` cycle: refine query → search → assess → answer or retry with a refined query, up to `max_rounds`.
- **Assess** — the LLM judging whether results answer the question (`sufficient`) and, if not, proposing a `new_query` + spoken `remark`.
- **Progress masking** — speaking "Searching for …" in a background task to overlap with network latency (`Speaker.say_soon`).
- **Prompt injection / neutralization / fencing** — treating web snippets as untrusted: wrapping in `<<<…>>>`, regex-filtering imperative injections to `[filtered]`, and instructing the model to ignore instructions inside fences.
- **SearXNG** — (roadmap, from user memory) a self-hosted metasearch engine with a JSON API (`format=json`, needs Redis) considered as a future keyless provider.

## Time & scheduling
- **Reminder** — a stored one-shot or recurring spoken alert (`kind='reminder'`).
- **Timer** — a named countdown, stored in the same table with `kind='timer'` + optional `label`.
- **Timespec** — a parsed temporal specification (`due_at` epoch, message, optional `interval`).
- **Management action** — a spoken edit to an existing reminder/event: cancel, reschedule, rename.
- **Recurrence / interval** — the seconds a reminder waits to re-arm after firing (None = one-shot).
- **Catch-up** — a single "while I was away…" summary on boot when multiple reminders came due offline.
- **Retry budget** — a per-reminder attempt counter that defers (not deletes) after `max_attempts`, so transient TTS failures don't lose a reminder.

## Calendar
- **Lead window** — the minutes before an event's start during which `CalendarWatcher` announces it (`watcher_lead_minutes`).
- **Blocklist** — title patterns (voice-added, config, or a description `hidden_tag`) that suppress unprompted announcements; explicit queries still show blocked events.
- **Dedupe** — announcing a given `(event_id, start_epoch)` only once; a reschedule (new start) re-announces.
- **Service account** — the Google-authenticated principal (read personal calendar, read/write the "Calcifer" calendar).
- **Speakable title** — an event title stripped of emoji/unspeakable symbols for clean TTS.

## Wake-word training
- **FPPH (False Positives Per Hour)** — the false-wake rate; `livekit`'s `find_best_threshold` maximizes recall subject to a target FPPH gate.
- **Gate passed** — `optimal_fpph <= target_fp_per_hour`; runtime should prefer gate-passing models.
- **Adversarial hard negatives** — phonetically near phrases (1–2 phoneme edits, e.g. "classify" vs "calcifer") that sharpen discrimination.
- **Smoke model** — a fast `_smoke`-suffixed training run proving the plumbing; the suffix is load-bearing (TUI cleanup keys on it).
- **VITS / RIRs / MUSAN / ACAV100M** — the TTS synthesizer for positive clips / room-impulse-response, ambient-noise, and large negative corpora used for augmentation.
- **ROCm / HIP / RDNA4 (gfx1201)** — the AMD GPU compute stack and architecture for the training venv (runtime needs no GPU).

## Deployment & specs
- **Composition root** — `app.py`, the one place concrete implementations are built and injected.
- **Frozen app / `_MEIPASS`** — the PyInstaller single-file binary and its temporary extraction root; cwd is set there to preserve config resolution; writable state redirects to XDG.
- **Wyoming protocol** — (reference-architecture lore) a Home-Assistant abstraction for swappable edge/server voice services.
- **Plumage / Feather** — fledge spec artifacts: a plumage is an umbrella capability spec (e.g. PLM-001 self-update); a feather is a vertical implementation slice (FTHR-001/002).
- **Restart-in-place** — the self-update capability: `os.execv` re-exec preserving PID and inherited pipes so the TUI supervisor sees no EOF.
- **ReAct loop** — reason→action→observation agent pattern the orchestrator's design gestures at.
