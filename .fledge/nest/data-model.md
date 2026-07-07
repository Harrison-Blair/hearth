---
generated: 2026-07-07T02:45:41Z
commit: 8d180f04862c48fdddc61804b81dafcd0f620344
agent: fledge-forager
fledge_version: unknown
---

# Data Model

Core types, dataclasses, and persistent schemas. The pipeline's shared records live in `assistant/core/events.py`; capabilities define their own dataclasses; two SQLite stores persist reminders and calendar state.

## Pipeline records — `assistant/core/events.py`

These flow down the pipeline and are the vocabulary skills and the orchestrator speak.

- **`WakeEvent`** — `name: str`, `score: float`. Wake-word detection with confidence; the score gates which ack-earcon pool is used.
- **`Turn`** — `role: "user"|"assistant"`, `content: str`. One message in conversation history.
- **`Command`** — `text: str`, `spoken: bool = True`, `history: list[Turn]`. A transcribed (or typed) utterance with conversation context. `spoken` distinguishes voice input (needs confirmation) from typed TUI input (trusted).
- **`ToolCall`** — `name: str`, `arguments: dict`. The LLM's tool selection, parsed from native or JSON response.
- **`Intent`** — `type: str`, `slots: dict = {}`, `raw_text: str = ""`. Routed intent; `slots` is populated from `ToolCall.arguments`.
- **`SkillResult`** — `speech: str`, `data: dict | None = None`, `success: bool = True`, `expects_reply: bool = False`. A skill's outcome. **`expects_reply=True` is the confirm-then-act seam**: it tells the pipeline to hold the skill and route the next utterance to `skill.handle_reply(cmd)` without re-orchestrating.

Related: **`ChatResponse`** (`assistant/llm/base.py`) — `content: str`, `tool_calls: list[ToolCall]`. **`Conversation`** (`assistant/core/conversation.py`) — a rolling deque of `Turn`, capped at `max_turns`; `history()` returns a copy.

## Tool schema shape — `assistant/skills/base.py`

Skills expose OpenAI function-calling schemas; the intent name *is* the tool name:

```json
{"type": "function",
 "function": {"name": "<intent>", "description": "...",
              "parameters": {"type": "object", "properties": {...}, "required": [...]}}}
```

Intents with no explicit `tool_specs` entry get a default single-parameter schema: `{"text": {"type": "string", "description": "the user's full request, verbatim"}}` (required). The `default=True` skill (`GeneralSkill`) contributes **no** tools — its reach is the model's direct answer.

## NLU / time types — `assistant/nlu/timespec.py`

- **`ReminderSpec`** — `due_at: float` (epoch), `message: str`, `interval: float | None` (repeat seconds; `None` = one-shot).
- **`ManagementAction`** — `action: "cancel"|"reschedule"|"rename"|"none"`, `target_index: int | None`, `new_at_time: str | None` (HH:MM 24h), `new_delay_seconds: float | None`, `new_message: str | None`.

## Calendar types — `assistant/calendar/`

- **`CalendarEvent`** (`base.py`) — `id`, `calendar_id`, `title`, `start` (tz-aware), `end` (optional), `all_day: bool`, `description`.
- **`ExtractedEvent`** (`extraction.py`) — `title`, `start`, `end` (tz-aware datetimes).
- **`EventManagementAction`** (`extraction.py`) — `action` (cancel/reschedule/rename/none), `target_index` (1-based | None), `new_date` (YYYY-MM-DD | None), `new_start_time` (HH:MM | None), `new_title`.
- **`EventReminderRequest`** (`extraction.py`) — `target_index` (1-based | None), `lead_minutes`.
- **`BlockRequest`** (`extraction.py`) — `action` (block/unblock/list/none), `pattern` (str | None).

## Search & weather types

- **`SearchResult`** (`assistant/search/base.py`) — `title`, `snippet`, `source` (domain for spoken attribution), `url`. `domain()` helper derives spoken attribution.
- **`Place`** (`assistant/weather/base.py`) — `name`, `latitude`, `longitude`.
- **`Forecast`** (`assistant/weather/base.py`) — `location`, `current` (dict: temp, apparent, description, wind, humidity), `daily` (list of dicts: date, weekday, description, high, low, precip_prob, precip, wind_max), `units` (dict).

## Persistent schemas (SQLite)

Both stores use WAL journal mode + `synchronous=NORMAL`, UTC epoch seconds for all timestamps, and synchronous methods (sub-millisecond statements on the event-loop thread).

### `ReminderStore` — `assistant/storage/reminders.py`

One table for reminders **and** timers (distinguished by `kind`). **`Reminder`** row: `id`, `due_at` (UTC epoch float, indexed), `speech`, `created_at`, `kind` (`"reminder"` | `"timer"`), `label` (optional, for named timers), `interval` (optional recurring seconds). Recurring reminders (non-null `interval`) re-arm to `now + interval` on fire instead of being deleted. Schema migration backfills `kind`/`label`/`interval` on legacy tables and reclassifies timer rows (`tests/test_reminder_store.py`).
Methods: `add`, `due(now)`, `pending(now, kind=None)`, `delete(id)`, `delete_pending(now, kind=None)`, `update_due(id, due_at)`, `update_speech(id, speech)`, `close()`.

### `CalendarStateStore` — `assistant/storage/calendar_state.py`

Two tables:
- **`announced`** — `(event_id, start_at)` primary key → `announced_at`. Dedupes announcements per event per start time; a rescheduled event gets a new key and is re-announced. Rows purged ~1 day (86400s) after start.
- **`blocked_titles`** — `pattern` primary key → `created_at`. Voice-added blocklist patterns, ordered by `created_at`.

Methods: `was_announced`, `mark`, `purge_before`, `add_blocked`, `remove_blocked`, `blocked_patterns`, `close()`.

## Config models — `assistant/core/config.py`

`Config` is the pydantic-settings root composed of ~20 nested `*Config` models. Full enumeration is in `entry-points.md`; notable sections: `AudioConfig`, `RecorderConfig`, `WakeConfig`, `SttConfig`, `LlmConfig`, `AgentConfig` (`tool_mode`, `max_tool_rounds`, `turn_timeout_s`), `PersonaConfig` (`enabled`, `strength`), `TtsConfig`, `ConversationConfig` (`followup_window_ms`, `max_history_turns`, `decision_*`, `end_phrases`), `CalendarConfig`, `WebSearchConfig`, `WeatherConfig`, `StorageConfig`, `SchedulingConfig`, `BargeinConfig`, `AecConfig`, `LoggingConfig`.

## Wake manifest — `models/wake/models.json`

Per-model entries (managed by `training/manifest.py`): `slug`, `phrase`, `model_path`, `fpph`, `recall`, `threshold`, `gate_passed`, `trained_at`. The runtime derives wake phrases from this manifest (or filename stems) via `assistant/wake/registry.py`.

## Eval/replay records — `tests/eval/`

- **`Case`** (`dataset.py`, frozen) — `utterance`, `tool: str|None`, `required_args: tuple`, `arg_contains: dict`, `note`.
- **Turn record** (captured JSONL) — `kind="turn"`, `text`, `history`, `route` (`"tool"|"direct"`), `tool`, `slots`, `speech`.
- **LLM records** — `kind ∈ {llm.complete, llm.chat, llm.chat_tools}`, `label`, `messages`, `system`, `tools`, `response`/`tool_calls`/`content`. Keyed for replay by SHA256 of canonical JSON.

## Open Questions

- No retention/archive policy is visible for `ReminderStore` beyond `CalendarStateStore.purge_before`; old reminders are removed only by explicit callers (`assistant-data` scout).
- Exact serialized shape of the `history` field in captured turn records (list of `Turn` as role/content dicts) is inferred, not confirmed (`tests-eval` scout).
