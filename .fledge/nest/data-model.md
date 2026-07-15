---
generated: 2026-07-15T22:30:28Z
commit: a8489b1afa55662a54ba66548a2e176584a3f387
agent: fledge-forager
fledge_version: 0.5.4
---

# Data Model

Core types, schemas, and persisted structures across the runtime, its config, its tests, and the wake-word training pipeline.

## Runtime configuration (`hearth/config.py`)

- `Settings` — root pydantic-settings model; loads `config.yaml` + `.env` + `HEARTH_*` env with the precedence described in conventions.md.
- `LLMConfig(backends, tiers, timeout, max_retries)`, `LLMBackend(base_url, model, api_key_env, supports_tools, supports_streaming, context_window, cost_tier, enabled)`.
- `LLMTiers(default, tool)` — maps a routing role to a backend name.
- `VeneerConfig(host, port)`, `ToolConfig(wikipedia_*)`.
- `AgentConfig(max_tool_rounds, turn_timeout_s, tool_mode, max_consult_rounds, consult_timeout_s)`.
- `PersonaConfig(enabled, system_prompt, brain_guard_prompt)`, `ConversationConfig(max_history_turns)`, `StorageConfig(db_path)`.
- `LoggingConfig(level, dir, file_name, max_bytes, backup_count, console, transcript_enabled, transcript_dir)`.

(all: hearth.md)

## Brain protocol (`hearth/brain/base.py`)

- `Capabilities(supports_tools, supports_streaming, context_window, cost_tier)`.
- `Message(role, content, tool_calls, tool_call_id)` — `role ∈ {"system", "user", "assistant", "tool"}`.
- `ToolCall(id, name, arguments)`.
- `ToolSpec(name, description, parameters, label)` — `parameters` is a JSON-schema dict describing the tool's arguments to the LLM.
- `BrainResult(text, tool_calls, finish_reason, backend, tier)`.
- `Brain` (Protocol) — `async complete(messages, tools) -> BrainResult`.
- `Selection(brain, tier, backend_name, reason)` (`hearth/brain/router.py`) — what `Router.select()` returns.

(hearth.md)

## Events & memory (`hearth/events.py`, `hearth/memory/`)

- `ToolActivity(turn_id, phase, label)` — `phase ∈ {"start", "end"}`; the only object serialized across the veneer WebSocket boundary.
- `EventSink = Callable[[object], Awaitable[None]]`; `null_sink` is a no-op implementation.
- `Event(id, session_id, turn_id, ts_utc, type, provenance, payload)` — one row of the append-only SQLite `EventLog`. `EVENT_TYPES = {user_input, routing_decision, tool_call, observation, final_answer, error}`.
- `EventLog(db_path)` — `.append(session_id, turn_id, type, provenance, payload) -> Event`, `.read_session(session_id, limit) -> list[Event]`. Append-only: no update/delete API (verified by `tests/test_event_log.py`).
- `EventReader(log)` — cursor-based pull: `.read_since(cursor, limit) -> list[Event]`, `.latest_cursor() -> int`.
- `Layer2Consumer` (Protocol, `hearth/memory/consumer.py`) + `pull_once()` — a seam for a not-yet-implemented downstream indexer (Graphiti/FalkorDB per Open Questions).

(hearth.md)

## Veneer wire protocol (`hearth/veneer/protocol.py`)

- `Request(turn_id, final_user_transcript)` — what `parse_request(raw)` produces from an incoming frame.
- Outbound wire messages (dict-shaped, not dataclasses per scout report): `answer_message(turn_id, text)`, `done_message(turn_id)`, `error_message(turn_id, message)`.
- `serialize(event)` — whitelist-only conversion of a `ToolActivity` to a dict; nothing else is serializable across this boundary today.

(hearth.md)

## Persisted storage

- **`hearth.db`** (SQLite, path from `StorageConfig.db_path`) — the `EventLog` table described above; auto-created on daemon start (root.md, hearth.md).
- **Rotating file logs** under `logging.dir`, rotated at `max_bytes` keeping `backup_count` files (root.md).
- **Per-session transcripts** under `logging.transcript_dir`, one human-readable file per `session_id` (root.md, hearth.md).

## Wake-word training data (`training/`, `models/`)

- **`training/calcifer.yaml`** training config (YAML): `model_name`, `target_phrases: list[str]`, `n_samples`/`n_samples_val`, `n_background_samples`/`n_background_samples_val`, `tts_batch_size`, `custom_negative_phrases: list[str]`, `noise_scales`/`noise_scale_ws`/`length_scales`/`slerp_weights: list[float]`, `data_dir`/`output_dir`, `augmentation` (dict: clip_duration, batch_size, rounds, background_paths, rir_paths), `model` (dict: model_type, model_size), `steps`/`learning_rate`/`weight_decay`/`label_smoothing`/`max_negative_weight`/`target_fp_per_hour`, `batch_n_per_class` (dict of positive/adversarial_negative/ACAV100M_sample/background_noise counts).
- **`models/wake/models.json`** manifest (per model, keyed by slug): `slug: str`, `phrase: str`, `model_path: str`, `fpph: float` (false positives per hour), `recall: float`, `threshold: float`, `gate_passed: bool`, `trained_at: str` (ISO 8601). Regenerated entries from orphaned `.onnx` files may lack eval metrics.
- **Livekit `eval.json`** (intermediate, read by `manifest.py upsert`): `optimal_fpph`, `optimal_recall`, `optimal_threshold`.
- **`models/wake/calcifer.onnx`** — the trained classifier artifact itself (binary, 962 KB); not a structured data type, consumed as an opaque model file.

(training.md, models.md)

## Test-local fixture types (`tests/`)

Not part of the production data model, but shape how the runtime types above are exercised:
- `_Config`, `_Agent`, `_Persona`, `_Conversation` — minimal stand-ins for the corresponding `hearth/config.py` models.
- OpenAI-like mocked response body: `{"choices": [{"message": {"role", "content", "tool_calls"}, "finish_reason"}]}`.
- Mocked tool-call structure: `{"id", "type": "function", "function": {"name", "arguments": json_string}}`.
- EventLog rows read back as `Event` namedtuples/dataclasses: `{"id", "session_id", "turn_id", "type", "role", "payload_json"}`.

(tests.md)

## Open Questions

- No data types were observed in `packaging/` or root-level files beyond configuration — `dependencies.md`/`entry-points.md` cover their behavior instead.
- Is `hearth.db`'s schema versioned/migrated anywhere, or is it created fresh (`CREATE TABLE IF NOT EXISTS`) with no migration path? Not visible in the assigned `hearth/` files (hearth.md).
