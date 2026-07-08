---
generated: 2026-07-07T22:56:23Z
commit: 58fb2ba9bbeefc5db7d530261bcb3450573048fa
agent: fledge-forager
fledge_version: unknown
---

# Conventions

Cross-cutting patterns observed across the codebase, reconciled from every module report. Follow these when adding or changing code; several are enforced by tests.

## Async everywhere

All pipeline-facing capability methods are `async def` (`LLMProvider.complete/chat/chat_tools/health`, `Skill.handle/handle_reply`, `SearchProvider.search`, `AudioIn.stream`, `STT.transcribe`, `TTS.synthesize`, provider CRUD). Blocking native work (Whisper, Piper, Speex, PortAudio callbacks, google-auth token refresh, `ddgs`) is offloaded via `asyncio.to_thread()` or callback/worker threads so the event loop stays free. `pytest` runs `asyncio_mode = "auto"`, so `async def test_...` needs no marker.

## Dependency injection by primitives

Components take primitive/config values in `__init__` (paths, thresholds, timeouts, endpoints, credentials), **never the whole `Config` object** — this keeps them unit-testable in isolation. `assistant/app.py` is the single composition root; it is the only place that constructs concrete implementations and injects them. No component imports another concrete component; the pipeline imports only `base.py` ABCs. Test seams accept injected fakes/clocks (e.g. `now=` callables, optional `model=` for the wake detector).

## Interface-per-capability & acyclic graph

Every capability is a package with a `base.py` ABC and concrete implementation(s) beside it. Shared cross-stage records live in `core/events.py` so capability packages pass them without importing each other. When adding a capability or swapping an implementation, code against the ABC — do not let the pipeline reach for a concrete type. Stub packages `sync/` and `connectivity/` (and the reserved base classes) are deliberate future seams, not dead code — don't delete them.

## Config is the single source of truth

Every device id, model path, threshold, and endpoint is a typed field on a `*Config` model in `core/config.py`, mirrored in both `config.yaml` and `default-config.yaml`. Precedence: explicit init args > `ASSISTANT_*` env vars > `config.yaml`. Nested keys use double underscore (`ASSISTANT_LLM__MODEL=llama3.2:3b`). **Never hard-code a path, threshold, or device id in a component** — add a tunable and mirror it in both YAML files. Secrets (`api_key`, `personal_calendar_id`, `calcifer_calendar_id`) default empty and are supplied via env only; they are masked in the logged config dump and never committed.

## Graceful degradation / fail-open

Remote is an optional accelerator, never a hard dependency. Providers health-check at boot and degrade with a logged warning rather than crashing. Fail-open is pervasive:
- LLM failure or turn timeout → route degrades to `GeneralSkill` (spoken offline message).
- Verify parse error → approve (fail-open).
- Revoice timeout/error/circuit-open → speak plain text.
- Keyed search provider failure → keyless tier with a spoken notice; `MultiSearch` drops failed providers and stays healthy if any provider is healthy.
- Every skill catches provider/LLM exceptions broadly (`except Exception`), logs, and returns `SkillResult(success=False)` with a spoken apology — no skill crashes the loop. Exceptions never escape async-loop boundaries.

## LLM provider conventions

- One pooled `httpx.AsyncClient` per provider instance, reused across calls, released via `aclose()`.
- `complete()`/`chat()` return plain `str`; only `chat_tools()` returns `ChatResponse` (content + `tool_calls`). System messages are *prepended* to the message list (Ollama shape), not sent as a separate wire field.
- Tool arguments handle both JSON-string (`json.loads`) and dict forms; default `{}` on parse failure.
- Retry classification (`OpenCodeZenProvider`): retry only 429/5xx/transport with exponential backoff + ±25% jitter (capped 2.0s); never retry 4xx-auth. `LLMResponseError` carries a `retryable: bool` flag set on malformed/empty 200 responses.
- `FallbackLLMProvider` catches any primary exception (`# noqa: BLE001`) and falls back; an *empty* response does **not** trigger fallback (the orchestrator handles empties).
- Structured logging: each call logs `extra={"data": {...}}` (kind, label, model, prompt/messages, latency_ms, tool info) for JSONL post-processing; `_clip(s, n)` truncates console text while full text stays in the data dict.

## Persona / revoice invariants (PLM-003)

- Persona is folded into **spoken output only** (`_speak`, verify `feedback`/`rewritten_speech`), never into routing decisions or structured JSON. Tool-decision and verify-decision prompts are persona-free — a hardening test enforces zero persona text in them.
- `_speak(text, voiced=False)`: unvoiced text passes through the `Revoicer` before TTS. LLM/persona-bearing skills mark `SkillResult.voiced=True` to bypass double-processing.
- **Digit-preservation guard**: revoiced output must retain every digit sequence from the plain text; any mutation discards the revoice and speaks plain.
- LLM-free spoken lines come from `persona.canned(key, enabled=, rng=)` (2–3 seeded variants per key); `canned()` results are always marked `voiced=True`. Persona v2 blocks are versioned (`_CALCIFER_V2_*`) so eval replays key on the new text.
- Circuit-breaker: after a revoice failure the `Revoicer` short-circuits to plain text for a bounded cooldown to prevent cascading latency.

## Storage & scheduling

- SQLite stores (`ReminderStore`, `CalendarStateStore`) use synchronous sub-millisecond statements on the event-loop thread (no `to_thread`); WAL mode, `synchronous=NORMAL`. Schema migrations backfill (e.g. legacy reminders → `kind='timer'`).
- Reminders/timers share one table, discriminated by `kind`. Recurring reminders carry `interval` (rearm to `now+interval`); one-shots are deleted after firing.
- Schedulers poll `standdown.active` each tick and skip while standing down (events remain and fire after resume). Audio output is serialized through `AudioArbiter`. Announcements route through the optional `Revoicer` (byte-identical output when `revoicer=None`).

## Style & tooling

- Ruff formatting, line-length 100 (`ruff check assistant tests`). Python pinned to 3.12 (`.python-version`; PyInstaller and native wheels require it).
- Naming: lowercase-underscore skill/intent names; test doubles prefixed `Fake*` or descriptive (`ScriptedLLM`, `TaggingRevoicer`).
- Heavy/native deps live in per-capability extras (`tts`, `wake`, `stt`, `vad`, `llm`, `nlu`, `scheduling`, `search`, `gcal`, `aec`, `tui`); tests run without them (everything native is stubbed).
- Text-first eval keys are content hashes, so any prompt/system/tool-schema change forces re-capture (see `testing.md`).

## TUI conventions

- One-directional dependency: `tui/` imports only `assistant.core.config.Config` and `assistant.wake.registry`; nothing under `assistant/` imports `tui`.
- Touch-first: full-width height-3 buttons, `Stepper`/`PickerScreen` instead of text inputs, no horizontal overflow at 40 columns (enforced by `tests/test_tui_screens.py`). One focused screen per job.
- Config editing sets `ASSISTANT_*` env overrides applied on daemon restart (Apply), or writes `config.yaml` and drops overrides (Save); it never silently rewrites config while running. Adding a setting = one `Field` entry in `config_schema.py:FIELDS`.
- Discovery providers fail soft (return `[]`/`False`, log a warning, never crash).

## Open Questions

- `Orchestrator.delegate_direct_answers` toggles passthrough vs. re-voice of no-tool answers; production value is set in `app.py` and not otherwise documented.
- The `think` field is described as Ollama-specific (suppress reasoning for JSON); whether other providers honor it is unspecified.
