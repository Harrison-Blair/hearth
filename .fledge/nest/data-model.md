---
generated: 2026-07-08T00:34:07Z
commit: 0a67e65dc3d33b2e9c911f1296eef515124fa678
agent: fledge-forager
fledge_version: unknown
---

# Data Model

Core types, config schema, and persisted tables. Pipeline records live in `assistant/core/events.py`; the config schema is `assistant/core/config.py`; persistence is SQLite under `assistant/storage/`.

## Pipeline records (`assistant/core/events.py`)

- `WakeEvent(name: str, score: float)` — a wake detection (`name` is the phrase; some tests refer to it as `phrase`).
- `Turn(role: str, content: str)` — `role` ∈ "user"/"assistant"; conversation history unit.
- `Command(text: str, spoken: bool, history: list[Turn])` — one routed utterance.
- `ToolCall(name: str, arguments: dict)` — an LLM-selected function call.
- `Intent(type: str, slots: dict, raw_text: str)` — routed direction; `type` is the skill/intent name, `slots` are the tool arguments.
- `SkillResult(speech: str, data: dict | None, success: bool, expects_reply: bool, restart: bool, voiced: bool)` — a skill's output. `voiced=True` means already persona-flavored (skip the revoicer); `restart=True` triggers in-place re-exec; `expects_reply=True` routes the next turn to `handle_reply`.

## LLM types (`assistant/llm/`)

- `ChatResponse(content: str = "", tool_calls: list[ToolCall] = [])` (`base.py`).
- `LLMResponseError(message, *, retryable: bool)` (`openai_compatible_provider.py`) — raised on non-JSON body, empty `choices`, or missing `message`; `retryable` distinguishes transient (truncated 200) from config bugs (4xx-auth).
- `GATEWAYS: dict[str, dict]` (`openai_compatible_provider.py`) — `{"opencode-zen": {"base_url": "https://opencode.ai/zen/v1", "extra_headers": {}}, "openrouter": {"base_url": "https://openrouter.ai/api/v1", "extra_headers": {}}}`. Add an entry to support a new gateway.
- OpenAI wire shapes: request `{"model", "messages":[{"role","content"}], "stream": false, ["response_format": {"type":"json_object"}], ["tools": [...]]}`; response `{"choices":[{"message":{"content", "tool_calls":[{"function":{"name","arguments": str|dict}}]}}]}`. Tool `arguments` arrive as a JSON string from OpenAI-style gateways (parsed via `json.loads`) or an object from Ollama.

## Verify (`assistant/core/verify.py`)

- `Verdict(decision, feedback, reason, rewritten_tool, rewritten_arguments, rewritten_speech)` — `decision` ∈ "approve"/"rewrite"/"reject"; pre-stage carries `rewritten_tool`/`rewritten_arguments`, post-stage carries `rewritten_speech`. Malformed JSON → safe defaults (fail-open). `Stage = Literal["pre","post"]`.

## Config schema (`assistant/core/config.py`)

`Config(BaseSettings)` composes 16 nested `*Config` `BaseModel`s. LLM- and secrets-relevant models first:

### LlmConfig (first-class for the upcoming feature)
Defaults reflect a fully-local Ollama profile; `config.yaml` overrides them to the OpenRouter profile (see below).
- Local/Ollama: `provider="ollama"`, `model="qwen2.5:3b-instruct"`, `host="http://localhost:11434"`, `timeout=60.0`, `health_timeout=5.0`, `num_ctx=8192`, `think=False`, `serve_cmd=["ollama","serve"]`.
- Gateway (OpenAI-compatible): `api_key=""`, `base_url=""` — `api_key` is the bearer token, read from `ASSISTANT_LLM__API_KEY` (never committed); blank `base_url` uses the provider's `GATEWAYS` default.
- Fallback: `fallback=""` (empty = none), `fallback_model=""` (defaults to `model`).
- `max_retries=2` (transient only; 4xx-auth never retried).
- `system_prompt` — voice-optimized default ("Answers are read aloud, reply in one or two short plain sentences…").

### WebSearchConfig (per-provider-secret precedent)
- `providers=["ddgs","wikipedia"]`, `language`, `region`, `result_count`, `max_results`, `timeout`, `max_snippet_chars`, `max_rounds`, `progress_updates`.
- Per-provider secrets/config: **`tavily_api_key=""`**, `tavily_endpoint="https://api.tavily.com/search"`, **`exa_api_key=""`**. These keyed-provider fields are the existing precedent for storing per-provider secrets on a config model; keys arrive via `ASSISTANT_WEB_SEARCH__TAVILY_API_KEY` / `ASSISTANT_WEB_SEARCH__EXA_API_KEY`.

### Other config models
- `AudioConfig` (input/output device, sample_rate, channels, block_size, output_volume, normalize flags/thresholds); `RecorderConfig` (VAD aggressiveness, silence_ms, max_ms, start_timeout_ms, min_speech_ms, preroll_frames); `WakeConfig` (model_path(s), threshold, score_interval, trigger_frames, confident_threshold; `model_refs()`, `phrases()`); `SttConfig` (model, device, compute_type, cpu_threads, language, beam_size, vad_filter, initial_prompt, thresholds, hallucination phrases).
- `PersonaConfig` (enabled=True, strength="terse"|"expansive", revoice_enabled, revoice_timeout_s); `AgentConfig` (tool_mode "native"/"json"/"auto", max_tool_rounds, turn_timeout_s); `VerifyConfig` (enabled, pre, post, max_verify_rounds, spoken_feedback).
- `TtsConfig` (voice, model_path, length_scale, ack_phrases, unsure_ack_phrases, ack_delay_s); `StorageConfig` (db_path); `SchedulingConfig` (poll_seconds).
- `WeatherConfig` (latitude, longitude, location_name, timezone, unit fields, forecast_days, endpoints); `CalendarConfig` (enabled, credentials_path, calendar ids, timeout, watcher settings, blocked_titles, hidden_tag); `ConversationConfig` (enabled, followup_window_ms, max_history_turns, decision_* fields, decline/end phrase lists).
- `AecConfig` (enabled=False, frame_ms, filter_length_ms, extra_delay_ms); `BargeInConfig` (enabled, threshold, trigger_frames); `LoggingConfig` (level, dir, file_enabled, file_level, rotate_max_bytes, rotate_backups, runs_to_keep).

## NLU / calendar extraction types

- `ReminderSpec(due_at: float, message: str, interval: float | None)`, `ManagementAction(action, target_index, new_at_time, new_delay_seconds, new_message)` (`assistant/nlu/timespec.py`).
- `ExtractedEvent(title, start, end)`, `EventManagementAction(action, target_index, new_date, new_start_time, new_title)`, `EventReminderRequest(target_index, lead_minutes)`, `BlockRequest(action, pattern)` (`assistant/calendar/extraction.py`).

## Capability value types

- `SearchResult(title, snippet, source, url)` (`assistant/search/base.py`) — `source` is the domain; a Tavily synthesized answer rides as a `SearchResult` with `source="tavily"`.
- `Place(name, latitude, longitude)`, `Forecast(location, current: dict, daily: list[dict], units: dict)` (`assistant/weather/base.py`).
- `CalendarEvent(id, calendar_id, title, start, end, all_day, description)` (`assistant/calendar/base.py`; `start`/`end` tz-aware).

## Persisted SQLite (`assistant/storage/`)

Both stores open with `journal_mode=WAL, synchronous=NORMAL`; timestamps are UTC epoch seconds; methods are synchronous single statements run on the event loop.

- `reminders` (`storage/reminders.py`): `id INTEGER PK AUTOINCREMENT, due_at REAL, speech TEXT, created_at REAL, kind TEXT DEFAULT 'reminder', label TEXT, interval REAL`; index `ix_reminders_due(due_at)`. Legacy DBs are migrated (ALTER adds `kind`/`label`/`interval`). `Reminder(id, due_at, speech, kind, label, interval)`. `kind` ∈ "reminder"/"timer"; non-null `interval` = recurring.
- `announced_events` (`storage/calendar_state.py`): `event_id TEXT, start_at REAL, announced_at REAL, PK(event_id, start_at)` — watcher dedup; purged daily.
- `blocked_titles` (`storage/calendar_state.py`): `pattern TEXT PK, created_at REAL` — voice-added calendar blocklist patterns.

## TUI data types (`tui/`)

`Field(key: tuple, label, kind, options, lo, hi, step)` (`config_schema.py`, `FIELDS` list drives the config form). Discovery dataclasses (`discovery.py`): `OllamaModel`, `OllamaModelDetail`, `RegistryModel`, `RegistryTag`, `PullProgress`, `RegistryVoice`. `LogLine(timestamp, level, logger, message, raw)` (`logparse.py`).

## Config profiles (as shipped)

- `config.yaml` (committed active profile — post-PLM-004): `llm.provider: openrouter`, `model: openrouter/free`, `base_url: ''` (→ OpenRouter default), `api_key: ''` (supplied via `ASSISTANT_LLM__API_KEY`), `fallback: ollama`, `fallback_model: qwen3:14b`. `web_search.providers: [ddgs, wikipedia]`, `tavily_api_key: ''`, `exa_api_key: ''`.
- `default-config.yaml` (reference/reset source): same OpenRouter-primary shape but `fallback_model: qwen2.5:3b-instruct`; comments document a commented-out fully-local profile.
- `.env.example` (secrets template): documents `ASSISTANT_*` names; still shows an Ollama-primary example plus an "OpenCode Zen" section (`BASE_URL=https://opencode.ai/zen/v1`). See Open Questions.

## Open Questions
- `.env.example` has not been updated to the OpenRouter-primary profile now in `config.yaml`/`default-config.yaml`; its worked example still names Ollama/OpenCode Zen. Confirm whether this template lag is intentional before relying on it as the canonical secrets example.
