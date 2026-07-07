---
generated: 2026-07-07T22:56:23Z
commit: 58fb2ba9bbeefc5db7d530261bcb3450573048fa
agent: fledge-forager
fledge_version: unknown
---

# Data Model

The core data types that flow through the pipeline, the LLM contract types, capability payloads, configuration models, and the two SQLite schemas. Most are frozen-ish dataclasses in `core/events.py` or per-capability `base.py` files; configuration is pydantic-settings.

## Pipeline event records (`core/events.py`)

These are the shared cross-stage records — they live in `core/` so capability packages pass them without importing each other.

- `WakeEvent` — `name: str, score: float`. A detected wake word.
- `Turn` — `role: str, content: str`. One message in conversation history.
- `Command` — `text: str, spoken: bool, history: list[Turn]`. A routable user utterance (`spoken` distinguishes voice from TUI-typed).
- `ToolCall` — `name: str, arguments: dict`. The model's requested skill invocation.
- `Intent` — `type: str, slots: dict, raw_text: str`. Routed intent; tool-call arguments populate `slots`.
- `SkillResult` — `speech: str, data: dict | None, success: bool = True, expects_reply: bool = False, restart: bool = False, voiced: bool = False`. A skill's outcome. `restart` triggers self-update (PLM-001); `voiced=True` bypasses the revoice seam (PLM-003); `expects_reply` drives two-phase confirmations; empty `speech` + `data` signals "tool loop continues".

## LLM contract types (`llm/base.py`)

- `LLMProvider` (ABC) — `async complete(prompt, *, system=None, json=False, label="") -> str`; `async chat(messages, *, system=None, label="") -> str`; `async chat_tools(messages, *, system=None, tools=None, label="") -> ChatResponse`; `async health() -> bool`; `async aclose() -> None`.
- `ChatResponse` (dataclass, `base.py`) — `content: str = ""`, `tool_calls: list[ToolCall] = field(default_factory=list)`.
- `LLMResponseError` (exception, `opencode_zen_provider.py`) — carries `retryable: bool`; raised on malformed/empty 200 responses. `retryable=True` for empty choices, missing message, non-JSON/non-dict body; drives the retry decision alongside HTTP status.

Provider constructors (all primitives, no `Config`):
- `OllamaProvider(model, host, timeout, health_timeout, num_ctx, think)`.
- `OpenCodeZenProvider(model, api_key, base_url, timeout, health_timeout, max_retries, retry_backoff_s)`.
- `FallbackLLMProvider(primary, fallback)`.

## Verify types (`core/verify.py`)

- `Verdict` — `decision, feedback, reason, rewritten_tool, rewritten_arguments, rewritten_speech`. Pre-stage populates `rewritten_tool`/`rewritten_arguments`; post-stage populates `rewritten_speech`; malformed JSON fails open (approve).

## Capability payloads

**Search (`search/base.py`)**
- `SearchResult` — `title, snippet, source (domain), url`. Tavily's synthesized answer is embedded as a `SearchResult(source="tavily", title="answer")`.

**Weather (`weather/base.py`)**
- `Place` — `name, latitude, longitude`.
- `Forecast` — `location: str`, `current: dict` (temp, apparent, description, wind, humidity), `daily: list[dict]` (date, weekday, description, high, low, precip_prob, precip, wind_max), `units: dict` (temp/wind/precip symbols).

**Calendar (`calendar/base.py`, `calendar/extraction.py`)**
- `CalendarEvent` — `id, calendar_id, title, start (tz-aware), end, all_day: bool, description`.
- `ExtractedEvent` — `title, start, end`. `EventManagementAction` — `action, target_index, new_date (YYYY-MM-DD), new_start_time (HH:MM), new_title`. `EventReminderRequest` — `target_index, lead_minutes (default 15)`. `BlockRequest` — `action ("block"|"unblock"|"list"|"none"), pattern`.

**NLU timespec (`nlu/timespec.py`)**
- `ReminderSpec` — `due_at (epoch float), message, interval (seconds | None one-shot)`.
- `ManagementAction` — `action ("cancel"|"reschedule"|"rename"|"none"), target_index, new_at_time, new_delay_seconds, new_message`.

## Configuration (`core/config.py`)

`Config` (pydantic-settings `BaseSettings`) composes 18 sub-configs: `AudioConfig, RecorderConfig, WakeConfig, SttConfig, LlmConfig, PersonaConfig, AgentConfig, VerifyConfig, TtsConfig, StorageConfig, SchedulingConfig, WebSearchConfig, WeatherConfig, CalendarConfig, ConversationConfig, AecConfig, BargeInConfig, LoggingConfig`. Every field is mirrored in `config.yaml` and `default-config.yaml`.

Key models (see `dependencies.md`/`entry-points.md` for how they're consumed):

- **`LlmConfig`** (the next feature's focus) — `provider` (`ollama` | `opencode-zen`), `model`, `host`, `timeout`, `health_timeout`, `num_ctx`, `think`, `serve_cmd`, `api_key`, `base_url`, `fallback`, `fallback_model`, `max_retries`, `system_prompt`. `provider` selects the primary in `app.py:_build_one_llm`; `fallback`/`fallback_model` build the secondary wrapped in `FallbackLLMProvider`; `api_key`/`base_url`/`max_retries` feed `OpenCodeZenProvider`; `host`/`num_ctx`/`think` feed `OllamaProvider`.
- **`PersonaConfig`** — `enabled, strength (terse|expansive), revoice_enabled, revoice_timeout_s`.
- **`AgentConfig`** — `tool_mode (native|json|auto), max_tool_rounds, turn_timeout_s`.
- **`VerifyConfig`** — `enabled, pre, post, max_verify_rounds, spoken_feedback`.
- **`WebSearchConfig`** — `providers, language, region, result_count, max_results, timeout, max_snippet_chars, max_rounds, progress_updates, tavily_api_key, exa_api_key, endpoints`.
- **`WeatherConfig`** — `latitude, longitude, location_name, timezone (auto|IANA), unit fields, forecast_days, timeout, endpoints`.
- **`CalendarConfig`** — `enabled, credentials_path, personal_calendar_id, calcifer_calendar_id, timeout, watcher_enabled, watcher_poll_seconds, watcher_lead_minutes, blocked_titles, hidden_tag`.
- **`SttConfig`** — `model, device, compute_type, cpu_threads, language, beam_size, vad_filter, initial_prompt, no_speech_threshold, log_prob_threshold, hallucination_max_rms`.
- **`WakeConfig`** — `model_paths, threshold (0.66), score_interval, trigger_frames, confident_threshold (0.85)`.
- **`AudioConfig`/`RecorderConfig`/`TtsConfig`/`AecConfig`/`BargeInConfig`/`ConversationConfig`/`StorageConfig`/`SchedulingConfig`/`LoggingConfig`** — device/rate/threshold/path tunables (see `default-config.yaml` for the exhaustive list with inline comments).

## SQLite schemas (`storage/`)

**`ReminderStore` — `reminders` table** (`reminders.py`, WAL, `synchronous=NORMAL`):
`id INTEGER PK AUTOINCREMENT`, `due_at REAL NOT NULL` (indexed), `speech TEXT NOT NULL`, `created_at REAL NOT NULL`, `kind TEXT NOT NULL DEFAULT 'reminder'` (also `'timer'`), `label TEXT`, `interval REAL` (recurrence delta; NULL = one-shot). Dataclass `Reminder(id, due_at, speech, kind, label, interval)`.

**`CalendarStateStore`** (`calendar_state.py`, WAL, `synchronous=NORMAL`):
- `announced_events` — `event_id TEXT`, `start_at REAL`, `announced_at REAL`; PK `(event_id, start_at)` (rescheduled event = new `start_at` = re-announced).
- `blocked_titles` — `pattern TEXT PRIMARY KEY`, `created_at REAL`.

## TUI data types (`tui/`)

Discovery/display records: `OllamaModel`, `OllamaModelDetail`, `RegistryModel`, `RegistryTag`, `RegistryVoice`, `PullProgress`, `LogLine`/`ParsedLogLine`, `Field` (config-schema entry: `key: tuple, label, kind, lo/hi/step, options`).

## Eval types (`tests/eval/`)

`Case(utterance, tool, required_args, arg_contains, note)`, `CaseResult`, `TurnResult`, `ReplayProvider` (keyed by `replay_key(kind, label, payload)` SHA-256), `ReplayMiss` exception.

## Open Questions

- Exact field list on the daemon JSONL `turn` / `llm.*` capture records is inferred from `extract.py`/`replay.py`, not formally documented.
