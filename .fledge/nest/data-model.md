---
generated: 2026-07-17T06:36:02Z
commit: 2cf763f017cef0f330f2fb0df7157c947be1113a
agent: fledge-forager
fledge_version: 0.6.7
---

# Data Model

Core types, schemas, and structs defined across the runtime: config schema, brain boundary types, event log schema, wire protocol types, and the wake-word training manifest.

## Configuration schema (`hearth/config.py`)

`Settings` (Pydantic `BaseSettings`, `env_prefix="HEARTH_"`, `env_nested_delimiter="__"`, `env_file=".env"`, `extra="ignore"`) aggregates exactly 8 top-level sections — no more exist yet (no `audio`/`wake`/`stt`/`tts`/`verify`/`scheduling`/`calendar`, per root `CLAUDE.md` and confirmed by scout read):

- `LLMConfig` — `backends: dict[str, LLMBackend]`, `tiers: LLMTiers`, `timeout`, `max_retries`; `resolve_tier(tier)` method.
  - `LLMBackend` — `base_url`, `model`, `api_key_env`, `supports_tools`, `supports_streaming`, `context_window`, `cost_tier`, `enabled`; `resolve_api_key()` reads from `os.environ`.
  - `LLMTiers` — `default`, `tool` (tier role → backend name mapping).
- `VeneerConfig` — `host`, `port`.
- `ToolConfig` — `wikipedia_enabled`, `wikipedia_language`, `wikipedia_endpoint`, `wikipedia_result_count`, `wikipedia_max_chars`, `wikipedia_timeout`.
- `AgentConfig` — `max_tool_rounds`, `turn_timeout_s`, `tool_mode` (native | json | auto), `max_consult_rounds`, `consult_timeout_s`.
- `PersonaConfig` — `enabled`, `system_prompt`, `brain_guard_prompt`.
- `ConversationConfig` — `max_history_turns`.
- `StorageConfig` — `db_path`.
- `LoggingConfig` — `level`, `dir`, `file_name`, `max_bytes`, `backup_count`, `console`, `transcript_enabled`, `transcript_dir`.

## Brain boundary types (`hearth/brain/base.py`) — frozen (FTHR-004/FTHR-006)

- `Message(role: str, content: str | None, tool_calls: list[ToolCall] | None = None, tool_call_id: str | None = None)`
- `ToolCall(id: str, name: str, arguments: dict)` — arguments already deserialized from JSON.
- `ToolSpec(name: str, description: str, parameters: dict, label: str)` — `label` is the phase/label surfaced to the veneer wire protocol.
- `Capabilities(supports_tools: bool, supports_streaming: bool, context_window: int, cost_tier: str)`
- `BrainResult(text, tool_calls=[], finish_reason="stop", backend="", tier="", model="", prompt_tokens=None, completion_tokens=None, reasoning_tokens=None, total_tokens=None, duration_s=None)` — additive-only (FTHR-013): new fields must be defaulted so existing call sites (`loop.py`, `tools/consult.py`) don't break. Token fields are `None` if the backend doesn't report usage.
- `Brain` — runtime-checkable `Protocol` with a `capabilities` attribute and async `complete(messages, tools) -> BrainResult`.
- `BrainError(reason: str, detail: str)` (`hearth/brain/errors.py`) — `reason` client-safe, `detail` internal-only, never leaks API keys.
- Router-internal: `Selection(brain: Brain, tier: str, backend_name: str, reason: str)`; `_BACKEND_CLASS_FOR_TIER: dict[str, type[_OpenAICompatBackend]]` = `{"default": LocalBackend, "tool": RemoteBackend}`.

## Event log schema (`hearth/memory/log.py`)

SQLite table `events`: `id` (autoincrement PK), `session_id`, `turn_id`, `ts_utc` (ISO timestamp), `type`, `provenance`, `payload_json`. Append-only — no update/delete method is exposed anywhere in `EventLog`. `Event` is a `@dataclass` mirror with `payload: dict` (deserialized). No schema validation on `type`/`provenance`/`payload` content beyond the column types — any dict is accepted as payload (flagged as an open question by the memory-tools scout).

`EventReader` (`hearth/memory/reader.py`) is a read-only cursor wrapper: `read_since(cursor, limit)` (cursor = last-seen event id, 0 = start of log), `latest_cursor()` (max id or 0 if empty). This is the seam a future Layer-2 background indexer attaches to — `Layer2Consumer` (`hearth/memory/consumer.py`) is currently just a `Protocol` + `NoOpConsumer` stub with a `pull_once()` proof-of-concept; no scheduler is wired.

## Runtime intermediate types (`hearth/loop.py`, `hearth/events.py`)

- `ToolActivity(turn_id, phase, label)` — the only event type the Loop↔Veneer boundary carries.
- `EventSink` — `Callable[[object], Awaitable[None]]`; default `null_sink()` is a no-op.
- `ReactRoundsMetrics(round_count, call_count, prompt_tokens, completion_tokens, duration_s, failed_count)` — mutated in place across `run_react_rounds()` calls.
- `ReactRoundsResult(result: BrainResult, metrics: ReactRoundsMetrics)`.

## Veneer wire protocol types (`hearth/veneer/protocol.py`)

- `Request(turn_id: str, final_user_transcript: str)` — inbound dataclass, parsed by `parse_request()`.
- Outbound message dicts (builder functions, no classes): `answer_message(turn_id, text) → {"type": "answer", "turn_id", "text"}`; `done_message(turn_id) → {"type": "done", "turn_id"}`; `error_message(turn_id, message) → {"type": "error", "turn_id", "message"}`.
- `serialize(event: ToolActivity) → dict` whitelists exactly `type`, `turn_id`, `phase`, `label` — raises `TypeError` on any other event type.

## Wake-word training manifest (`training/manifest.py`, standalone — no hearth imports)

`models/wake/models.json`:
```json
{
  "<slug>": {
    "phrase": "<display-name>",
    "model_path": "models/wake/<slug>.onnx",
    "fpph": <float>,
    "recall": <float>,
    "threshold": <float>,
    "gate_passed": <bool>,
    "trained_at": "<ISO-timestamp>"
  }
}
```
Also: `training/work/<model>.yaml` (effective training config after CLI overrides, kept for reproducibility), `training/output/<model>/<model>.onnx` (exported classifier, copied to `models/wake/`), `training/output/<model>/<model>_eval.json` (`optimal_recall`/`optimal_fpph`/`optimal_threshold`, parsed by `manifest.upsert`, which derives `gate_passed` as `optimal_fpph <= target_fpph` — the gate flag is a manifest field, not an eval-file field). Currently `models/wake/vesta.onnx` (960,600 bytes) is the only artifact checked into the repo; nothing in `hearth/` loads it yet.

## Open Questions

- Are there constraints on event `type` vs. `provenance` vs. `payload` content in the event log, or is any dict accepted at runtime? (`log.py` shows no validation.)
- What is the exact enumerated set of event `type` values in current use (e.g. `routing_decision`, `observation`, `user_input`, `final_answer`, `tool_call` are referenced across scout reports but no canonical enum was found)?
