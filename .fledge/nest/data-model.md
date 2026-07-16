---
generated: 2026-07-15T23:27:05Z
commit: e41ba8a73a56364e7c3bb1acf1332cadab817e45
agent: fledge-forager
fledge_version: 0.5.5
---

# Data Model

Core types and schemas defined in `hearth/`, plus the on-disk formats used by the training pipeline.

## Brain boundary types (`hearth/brain/base.py`)

- `Capabilities(supports_tools, supports_streaming, context_window, cost_tier)`
- `ToolCall(id, name, arguments)`
- `Message(role, content, tool_calls, tool_call_id)`
- `ToolSpec(name, description, parameters, label)`
- `BrainResult(text, tool_calls, finish_reason, backend, tier)`
- `Brain` — frozen protocol implemented by `local.py`/`remote.py` backends

## Errors (`hearth/brain/errors.py`)

- `BrainError(reason, detail)` — `reason` client-safe, `detail` internal-only diagnostic; never leaks secrets.

## Routing (`hearth/brain/router.py`)

- `Selection(brain, tier, backend_name, reason)` — result of `Router.select()`.

## Events (`hearth/events.py`)

- `ToolActivity(turn_id, phase, label)` — `phase` is `"start"` or `"end"`.
- `EventSink = Callable[[object], Awaitable[None]]`; `null_sink` — no-op default.

## Event log (`hearth/memory/log.py`)

- `Event(id, session_id, turn_id, ts_utc, type, provenance, payload)` — `type` in `{user_input, routing_decision, tool_call, observation, final_answer, error}`.
- Backing store: sqlite (`hearth.db` by default, `storage.db_path`), `events` table, append-only (no update/delete). `EventLog.append(...) -> Event`; `read_session(session_id, limit) -> list[Event]` (oldest-first).
- `EventReader.read_since(cursor, limit) -> list[Event]` (ascending by id); `latest_cursor() -> int` — the read-only Layer-2 seam.

## Wire protocol (`hearth/veneer/protocol.py`)

- `Request(turn_id, final_user_transcript)` — inbound.
- Outbound message shapes (whitelisted by `serialize`): `answer` (`type, turn_id, text`), `tool_activity` (`type, turn_id, phase, label`), `done` (`type, turn_id`), `error` (`type, turn_id, message`).

## Configuration schema (`hearth/config.py`, pydantic-settings)

- `LLMBackend(base_url, model, api_key_env, supports_tools, supports_streaming, context_window, cost_tier, enabled)` with `resolve_api_key() -> Optional[str]`.
- `LLMTiers(default, tool)` — backend names per tier role.
- `LLMConfig(backends, tiers, timeout, max_retries)` with `resolve_tier(tier) -> LLMBackend`.
- `VeneerConfig(host, port)`.
- `ToolConfig` — flat Wikipedia settings (language, result count, max chars, timeout, etc.).
- `AgentConfig(max_tool_rounds, turn_timeout_s, tool_mode, max_consult_rounds, consult_timeout_s)`.
- `PersonaConfig(enabled, system_prompt, brain_guard_prompt)`.
- `ConversationConfig(max_history_turns)`.
- `StorageConfig(db_path)`.
- `LoggingConfig(level, dir, file_name, max_bytes, backup_count, console, transcript_enabled, transcript_dir)`.

## Training-pipeline on-disk formats (`training/`, `models/wake/`)

- `calcifer.yaml` (and per-phrase derivatives) — YAML dict: `model_name`, `target_phrases`, sample/step counts, `custom_negative_phrases`, TTS variation params (`noise_scales`, `length_scales`, `slerp_weights`), `augmentation` block (`clip_duration`, `batch_size`, `rounds`, `background_paths`, `rir_paths`), `model` block (`model_type`, `model_size`), training hyperparams (`steps`, `learning_rate`, `weight_decay`, `label_smoothing`, `max_negative_weight`, `target_fp_per_hour`), `batch_n_per_class`.
- `models/wake/models.json` — `{<slug>: {phrase, model_path, fpph?, recall?, threshold?, gate_passed?, trained_at}}`; `gate_passed = optimal_fpph <= target_fpph`.
- `<model>_eval.json` (livekit output, consumed by `manifest.py upsert`) — `optimal_fpph`, `optimal_recall`, `optimal_threshold`.
- `models/wake/calcifer.onnx` — the exported binary classifier; **no corresponding Python type in `hearth/` yet** since nothing in the runtime loads it (see `architecture.md`).

## Open Questions

- Exact `payload_json`/`payload` schema per `Event.type` (routing_decision, observation, etc.) is not formally documented anywhere in the assigned source — inferred only from usage.
