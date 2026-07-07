---
generated: 2026-07-07T07:06:00Z
commit: 02f839d7a116780b02510c2d5b339c23c64a51f5
agent: fledge-forager
fledge_version: unknown
---

# Data Model

Core types, dataclasses, config models, and persistent schemas, organized by concern. File references point at the definition site.

## Cross-stage pipeline records (`assistant/core/events.py`)
These flow down the pipeline; kept in `core/` to keep the dependency graph acyclic.

- `WakeEvent(name: str, score: float)` — a wake-word activation.
- `Turn(role: str, content: str)` — one message in conversation history (`"user"`/`"assistant"`).
- `Command(text: str, spoken: bool = True, history: list[Turn] = [])` — a transcribed utterance to route.
- `ToolCall(name: str, arguments: dict = {})` — a tool the model asked to run.
- `Intent(type: str, slots: dict = {}, raw_text: str = "")` — a routed intent; `slots` populated from tool arguments.
- `SkillResult(speech: str, data: dict | None = None, success: bool = True, expects_reply: bool = False)` — outcome of a skill handling a command.

## Verification (`assistant/core/verify.py`)
- `Verdict(decision: str, feedback: str = "", rewritten_tool: str = "", rewritten_arguments: dict = {}, rewritten_speech: str = "")` — `decision ∈ {approve, rewrite, reject}`. `feedback`/`rewritten_speech` are persona-flavored (spoken); `rewritten_tool`/`rewritten_arguments` are neutral (routing).

## LLM (`assistant/llm/base.py`)
- `ChatResponse(content: str = "", tool_calls: list[ToolCall] = [])` — union response: spoken content, tool calls, or both.
- `LLMResponseError(message, *, retryable: bool)` — distinguishes transient (429/5xx, truncated 200) from permanent (4xx auth) failures; drives retry-vs-give-up.

## Search — the focus area (`assistant/search/base.py`)
- `SearchResult` (`@dataclass`):
  - `title: str` — result heading.
  - `snippet: str` — brief excerpt (truncated to `max_snippet_chars`).
  - `source: str` — bare domain for spoken attribution (e.g. `"bbc.com"`) or a hardcoded label (`"wikipedia"`); derived via `domain(url)`.
  - `url: str = ""` — full URL; empty for backends that don't supply one.
- `SearchProvider` (ABC) — the seam every backend implements: `async search(query: str, *, count: int) -> list[SearchResult]`, `async health() -> bool`, `async aclose() -> None`.
- `domain(url) -> str` — `urlparse(url).netloc` minus a leading `www.`; `""` on invalid input.
- Provider-internal request/response shapes (not persisted):
  - `DdgsSearch`: `ddgs.DDGS.text()` rows `{href, title, body}` → `SearchResult{url, title, snippet}`.
  - `WikipediaSearch`: Action API `action=query&generator=search&gsrsearch=…&prop=extracts&exintro=1&explaintext=1` → `{"query":{"pages":{pageid:{title, extract, index}}}}`, sorted by `index`.
  - `MultiSearch` merge: round-robin by rank across provider lists; dedup key `url.rstrip("/").lower() or f"{source}:{title}"`; capped at `max_results`.
- `WebSearchSkill._Verdict` (internal, `assistant/skills/web_search.py`) — parsed assess response: `sufficient` + either `answer` (+ source urls) or `new_query` + spoken `remark`.

**Adding an AI-first provider (Tavily/Exa/Brave):** map the API's title/snippet/source/url onto `SearchResult`, implement `search`/`health`/`aclose`, and take API key + tuning as `__init__` primitives (no new cross-stage type is needed).

## NLU time specs (`assistant/nlu/timespec.py`)
- `ReminderSpec(due_at: float, message: str, interval: float | None = None)` — epoch due time, text, optional repeat cadence (seconds).
- `ManagementAction(action, target_index, new_at_time, new_delay_seconds, new_message)` — `action ∈ {cancel, reschedule, rename, none}`.

## Calendar (`assistant/calendar/`)
- `CalendarEvent(id, calendar_id, title, start, end, all_day, description)` — `start` tz-aware; `end: datetime | None` (`base.py`).
- `ExtractedEvent(title, start, end)`, `EventManagementAction(action, target_index, new_date, new_start_time, new_title)`, `EventReminderRequest(target_index, lead_minutes)`, `BlockRequest(action, pattern)` — LLM-extraction results (`extraction.py`).

## Weather (`assistant/weather/base.py`)
- `Place(name, latitude, longitude)` — geocode result.
- `Forecast(location, current: dict, daily: list[dict], units: dict)` — `current` keys: temp/apparent/description/wind/humidity; `units`: temp/wind/precip.

## Persistent storage (SQLite)

### `reminders` table (`assistant/storage/reminders.py`)
Backs both reminders and timers (discriminated by `kind`).
```sql
CREATE TABLE IF NOT EXISTS reminders (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    due_at     REAL    NOT NULL,
    speech     TEXT    NOT NULL,
    created_at REAL    NOT NULL,
    kind       TEXT    NOT NULL DEFAULT 'reminder',   -- 'reminder' | 'timer'
    label      TEXT,                                   -- optional timer name
    interval   REAL                                    -- recurring period (s); NULL = one-shot
);
CREATE INDEX IF NOT EXISTS ix_reminders_due ON reminders (due_at);
```
- `Reminder(id, due_at, speech, kind, label, interval)` dataclass. Migration adds `kind`/`label`/`interval` to legacy DBs; a one-time backfill retags old `'Your timer is done.'` rows as timers.
- WAL mode + `PRAGMA synchronous=NORMAL` so scheduler reads overlap writes.

### `announced_events` + `blocked_titles` tables (`assistant/storage/calendar_state.py`)
```sql
CREATE TABLE IF NOT EXISTS announced_events (
    event_id     TEXT NOT NULL,
    start_at     REAL NOT NULL,
    announced_at REAL NOT NULL,
    PRIMARY KEY (event_id, start_at)
);
CREATE TABLE IF NOT EXISTS blocked_titles (
    pattern    TEXT PRIMARY KEY,
    created_at REAL NOT NULL
);
```
Dedup key `(event_id, start_at)` — a rescheduled event gets a new `start_at` and re-announces.

## Configuration models (`assistant/core/config.py`)
Top-level `Config(BaseSettings)` with `model_config`: `yaml_file="config.yaml"`, `env_prefix="ASSISTANT_"`, `env_nested_delimiter="__"`; precedence init > env > yaml. Nested fields: `audio`, `recorder`, `wake`, `stt`, `llm`, `persona`, `agent`, `verify`, `tts`, `storage`, `scheduling`, `web_search`, `weather`, `calendar`, `conversation`, `aec`, `barge_in`, `logging`. Notable models:

- **`WebSearchConfig`** (focus area) — `providers: list[str] = ["ddgs", "wikipedia"]` (fan-out set; order = merge priority), `language: str = "en"`, `region: str = "us-en"`, `result_count: int = 3` (per provider), `max_results: int = 5` (merged cap fed to LLM), `timeout: float = 10.0`, `max_snippet_chars: int = 500`, `max_rounds: int = 2` (agentic rounds), `progress_updates: bool = True`. A new provider is opted in by adding its key to `providers`; any provider-specific setting (API key, endpoint) should be added here as a typed field and mirrored in both YAML files.
- **`LlmConfig`** — `provider`, `model`, `host`, `timeout`, `health_timeout`, `num_ctx`, `think`, `serve_cmd`, `api_key`, `base_url`, `fallback`, `fallback_model`, `max_retries`, `system_prompt`.
- **`AgentConfig`** — `tool_mode` (native|json|auto), `max_tool_rounds`, `turn_timeout_s`.
- **`VerifyConfig`** — `enabled`, `pre`, `post`, `max_verify_rounds`, `spoken_feedback`.
- **`WakeConfig`** — `model_path`, `model_paths`, `model_name`, `threshold`, `score_interval`, `trigger_frames`, `confident_threshold`; methods `model_refs()`, `phrases()`.
- **`SttConfig`** — model/device/compute_type/language/beam_size/vad_filter/thresholds/`hallucination_phrases`/`hallucination_max_rms`.
- **`AudioConfig`**, **`RecorderConfig`**, **`TtsConfig`**, **`PersonaConfig`**, **`StorageConfig`**, **`SchedulingConfig`**, **`WeatherConfig`**, **`CalendarConfig`**, **`ConversationConfig`**, **`AecConfig`**, **`BargeInConfig`**, **`LoggingConfig`** — see `assistant/core/config.py` for full field lists.

## Pipeline state values (`assistant/core/state.py`)
`"idle"`, `"paused"`, `"listening"`, `"thinking"`, `"speaking"`, `"no_speech"`, `"error"` — emitted as `@@STATE {json}` for the TUI.

## Training manifest (`models/wake/models.json`, `training/manifest.py`)
`{ slug: { phrase, model_path, fpph, recall, threshold, gate_passed, trained_at } }`. `gate_passed = optimal_fpph <= target_fp_per_hour`. Consumed by `assistant/wake/registry.py` for phrase derivation and by the TUI/`select` for model choice.

## Open Questions
- `Skill.tool_specs` is a class-level mutable `{}` (`skills/base.py:35`); whether a subclass could mutate the shared default is unverified.
- `WebSearchConfig` has no field for a keyed provider's API key yet — the AI-first work will need to add one (and decide whether it lives in config or `.env` only, per the verify-loop spec's precedent of keeping secrets in `.env`).
