---
generated: 2026-07-07T02:45:41Z
commit: 8d180f04862c48fdddc61804b81dafcd0f620344
agent: fledge-forager
fledge_version: unknown
---

# Domain

Glossary of the business/domain vocabulary this codebase embodies. Terms are grouped by area; where a term maps to code, the file is noted.

## The assistant

- **Calcifer** — the assistant's name (from the fire demon). Also the name of the custom wake word, its ONNX model (`models/wake/calcifer.onnx`), the persona voice, and the dedicated read-write Google Calendar for assistant-created events.
- **Offline-first** — all processing runs locally; cloud services (calendar, search, weather, Ollama-served LLM) are optional accelerators with local fallbacks and graceful degradation.
- **Daemon** — the always-listening `python -m assistant.app` process.
- **Persona** — the Calcifer voice tone (`terse`|`expansive`, `PersonaConfig`), appended only to final-reply prompts (`assistant/core/persona.py`).

## Voice pipeline

- **Wake word** — the offline spoken trigger ("Calcifer"), scored continuously by a local ONNX detector; emits a `WakeEvent` with a confidence score that gates the ack earcon.
- **VAD (Voice Activity Detection)** — per-frame speech/silence classification (webrtcvad); ends recording after trailing silence (`assistant/audio/recorder.py`).
- **STT (Speech-to-Text)** — transcription (faster-whisper).
- **TTS (Text-to-Speech)** — synthesis (Piper ONNX voice).
- **Utterance / Turn** — a user's transcribed command / one request-reply cycle. `Turn` is also the history dataclass.
- **Conversation** — a multi-turn exchange sharing history; ends on silence, an **end phrase** ("goodbye", "i'm done" — substring match), or a **decline phrase** ("no") after a check-in.
- **Follow-up** — a turn captured within `followup_window_ms` of silence, requiring no wake word.
- **Continuation decision** — the LLM's post-reply choice of `listen` / `confirm` / `end`, made while the reply is spoken; degrades to silent `listen` when offline (`pipeline._decide_continuation`).
- **Barge-in** — the user speaks (wake word / raised score) over the assistant's reply; playback is cut and the mic reopens without ack. Requires AEC to avoid self-triggering.
- **Earcon** — a synthesized non-speech cue (wake ding, end tone, check-in chime, no-speech) generated in code (`assistant/audio/earcon.py`).
- **Preroll** — audio frames captured *before* the wake word (default 6 × 80 ms) to recover speech clipped by detection latency.
- **Hallucination filter** — dropping known Whisper artifacts (e.g. "thank you") when RMS is low, treating them as silence.
- **Tap** — a synchronous per-frame observer on the mic (`set_tap`) that fires even during playback, enabling barge-in wake scoring (`assistant/audio/mic_hub.py`).
- **AEC (Acoustic Echo Cancellation)** — subtracting the speaker's far-end output from the near-end mic signal so the assistant doesn't hear itself (`assistant/audio/aec.py`, Speex).
- **RMS / peak normalize** — audio level measures; `normalize_peak` gates on an RMS floor to avoid amplifying noise.

## Orchestration & skills

- **Skill** — a pluggable handler for one or more intents (`Skill` subclass); the unit of capability. Registered on the `SkillRegistry`.
- **Intent** — a named route destination (e.g. `weather`, `reminder`, `calendar_query`) with extracted **slots** (arguments).
- **Tool / tool call** — the LLM's decision to invoke a skill intent, exposed as an OpenAI function schema; the intent name *is* the tool name.
- **Tool spec** — a skill's declared metadata (description + JSON-schema parameters) for an intent.
- **Orchestrator** — the LLM tool-calling loop (`assistant/core/orchestrator.py`) that decides tool-vs-direct-answer and degrades to the default skill.
- **Default skill** — the `default=True` skill (`GeneralSkill`) that catches unrouted intents and direct answers; contributes no tools.
- **Direct answer** — an LLM reply with no tool call.
- **Delegation** — routing a direct answer through `GeneralSkill` as a **draft** to be re-voiced (not re-derived) in persona.
- **Confirm-then-act** — a skill returns `expects_reply=True` to ask a confirmation; the pipeline routes the next utterance to `handle_reply` without re-orchestrating (`ReminderSkill` bulk delete). The seam a self-update confirmation would reuse.
- **Sign-off** — a spoken closing line; `StandDownSkill` has quirky ones ("standing down until you wake me from the screen"). No dedicated sign-off subsystem exists yet.

## Runtime state & scheduling

- **Stand-down** — a user-requested pause ("stop listening"); suppresses wake detection and proactive speech for a duration or indefinitely; shared `StandDown` polled by pipeline/scheduler/watcher/control (`assistant/core/standdown.py`). Cleared by `RESUME`, expiry, or restart.
- **Arbiter (AudioArbiter)** — the async lock serializing capture, playback, and proactive announcements so they never collide.
- **Reminder / Timer** — scheduled tasks in the same SQLite store, distinguished by `kind`; a **recurring** reminder has a non-null `interval` and re-arms instead of deleting; a **timer** carries an optional `label` (e.g. "pasta timer").
- **Catch-up** — on boot, the `ReminderScheduler` coalesces all reminders that came due while offline into one "While I was away…" announcement.
- **Lead window** — the minutes-before-event window in which `CalendarWatcher` announces an event.
- **Dedupe key** — `(event_id, start_at)` for calendar announcements; a rescheduled event gets a new key and re-announces.
- **Blocklist** — calendar event-title patterns muted from announcements; three sources (voice-added in `CalendarStateStore`, config patterns, `[hidden]` tag in event description).
- **Speakable title** — an event title with emoji/unspeakable Unicode stripped for TTS.
- **WMO code** — World Meteorological Organization weather code → short spoken phrase (Open-Meteo).

## Search

- **Provider** — a search backend (`WikipediaSearch`, `DdgsSearch`); `MultiSearch` fans out and merges.
- **Agentic multi-round search** — `WebSearchSkill` refines a query, searches, assesses sufficiency via LLM JSON verdict, and retries (`web_search.py`).
- **Prompt-injection defense** — fencing snippets with `<<<`/`>>>`, neutralizing injection patterns, and length-capping refined queries — defense-in-depth against untrusted web content.
- **Progress speech** — speaking a remark while the next search runs, to overlap latency.

## Monitor TUI

- **Supervisor (DaemonSupervisor)** — the TUI component that spawns/restarts/stops the daemon child and carries the control channel over its stdin/stdout.
- **Control channel** — the stdin line protocol from TUI to daemon (`TEXT`/`SET`/`SAY`/`LISTEN`/`CANCEL`/`STOP`/`RESUME`).
- **State feed (`@@STATE`)** — the daemon's stdout JSON marker lines driving the Now screen.
- **Channel** — one of the three log panes (app / llm / ollama).
- **Override** — an `ASSISTANT_*` env var set by the TUI config form, applied on daemon (re)start.
- **Portrait constraint** — every screen must fit 40×30 cells (320×480 touch display), no horizontal overflow.

## Wake-word training (peripheral)

- **FPPH (False Positives Per Hour)** — the wake false-alarm rate; the training **gate** targets ≤ target FPPH (`gate_passed`).
- **Adversarial hard negatives** — phonetically near-miss phrases (1–2 phoneme edits) that must not trigger (e.g. "calcify" vs "calcifer").
- **Manifest** — `models/wake/models.json`, the registry of trained models with eval metrics and thresholds.
- **Slug** — a filesystem-safe model id derived from a phrase (lowercase, underscores).
- **Smoke run** — a reduced-scale end-to-end training run to verify plumbing.
- **SLERP / augmentation / RIR / MUSAN / ACAV100M** — TTS speaker blending and reverb/noise/negative-sample data used to make the wake model robust.

## Deployment / packaging

- **Composition root** — `assistant/app.py`, the only place providers are constructed and wired.
- **Interface-per-capability** — each capability = a package with an ABC (`base.py`) + concrete implementation(s).
- **Frozen binary** — the PyInstaller single-file `dist/assistant-$(uname -m)`; runs via `packaging/entrypoint.py`.
- **onefile / `sys._MEIPASS`** — PyInstaller extracts the bundle to a temp dir at runtime; the entrypoint `chdir`s there.
- **XDG data dir** — `~/.local/share/assistant/` for the writable SQLite DB and HF cache, keeping the bundle read-only.
