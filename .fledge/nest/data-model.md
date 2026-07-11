---
generated: 2026-07-10T22:45:49Z
commit: ce70f988da5255908dc6a9bb3dc26206b5e57b36
agent: fledge-forager
fledge_version: 0.3.0
---

# Data Model

The shapes of data this repo defines: the runtime configuration schema (values only — the Pydantic classes that will parse it live in the absent `assistant/`), the training pipeline's config/registry files, and the secrets schema.

## Runtime configuration schema (`config.yaml` / `default-config.yaml`)

A single nested config object with 18 top-level sections, loaded via `pydantic-settings`. `config.yaml` is the active file; `default-config.yaml` mirrors the same schema with an inline comment per field (read it to understand what a knob does). No Pydantic model classes exist on disk yet (they'd live in the absent `assistant/`) — this is the schema *shape*, inferred from the YAML values themselves:

- **audio** — I/O device, sample rate, normalization.
- **recorder** — VAD aggressiveness (0–3), silence/max/start timeouts, preroll.
- **wake** — `model_paths` (array of strings, written by `training/manifest.py select`), `threshold` (float, default 0.66), `score_interval`, `trigger_frames`, `confident_threshold` (0.85 default — scores at/above trigger "confident" ack phrases, below trigger "unsure" ack phrases).
- **stt** — `model` (e.g. `medium`, or `distil-whisper` on Pi), `compute` (e.g. `int8`), `device` (`cpu`).
- **llm** — `provider` (`ollama` | `opencode_zen` | `openrouter`), `model`, `host`, `timeout`, `health_timeout`, `num_ctx`, `think` (bool), `serve_cmd` (array, e.g. `["ollama", "serve"]`), `base_url`, `fallback`, `fallback_model`, `max_retries`. Active values: primary `openrouter`/`openrouter/free`, fallback `ollama`/`qwen3:14b`.
- **persona** — `enabled`, `strength` (e.g. `terse`), `revoice`.
- **agent** — `tool_mode` (`auto`), `max_tool_rounds` (3), `turn_timeout_s` (45).
- **verify** — pre/post gates, `max_verify_rounds` (2) — caps rejected tool-picks/answers per stage.
- **tts** — `voice` (`en_US-lessac-medium`), `model_path` (references `models/piper/en_US-lessac-medium.onnx`, **not present in this repo** — only the wake model is tracked), `ack_phrases`.
- **storage** — `db_path` (`assistant.db`, sqlite).
- **scheduling** — apscheduler-backed reminders.
- **web_search** — `providers` (`ddgs`, `wikipedia`; optionally Tavily/Exa via secrets).
- **weather** — coordinates (Atlanta), `timezone` (`auto`); Open-Meteo endpoints.
- **calendar** — `enabled`, `credentials_path` (`~/.config/calcifer/google-service-account.json`), `personal_calendar_id` (`harrison.blair.dev@gmail.com`), `calcifer_calendar_id` (a distinct calendar ID), `timeout`, `watcher_enabled`, `watcher_poll_seconds`, `watcher_lead_minutes`, `blocked_titles`, `hidden_tag`.
- **conversation** — `enabled`, `followup_window_ms` (6000 — silence duration that closes a conversation turn), `max_history` (12), `decision_enabled`, `end_phrases`.
- **aec** — `enabled` (false by default; native/build-sensitive).
- **barge_in** — `enabled` (false by default; interrupt playback on wake word).
- **logging** — `level` (`INFO`), file rotation under `logs/`.

## Secrets schema (`.env.example`)

Naming convention `ASSISTANT_<SECTION>__<PROVIDER>_API_KEY`, secrets only (see `conventions.md`):
- `ASSISTANT_LLM__OPENROUTER_API_KEY`
- `ASSISTANT_LLM__OPENCODE_ZEN_API_KEY`
- `ASSISTANT_WEB_SEARCH__TAVILY_API_KEY`
- `ASSISTANT_WEB_SEARCH__EXA_API_KEY`

## Training config schema (`training/calcifer.yaml`)

Loaded via `yaml.safe_load()` in `training/train.py`:
- `model_name` (str), `target_phrases` ([str]), `n_samples` / `n_samples_val` / `n_background_samples` / `n_background_samples_val` / `tts_batch_size` (int)
- `noise_scales` / `noise_scale_ws` / `length_scales` / `slerp_weights` ([float]) — TTS augmentation
- `data_dir` / `output_dir` (str)
- `augmentation`: `{clip_duration, batch_size, rounds, background_paths, rir_paths}`
- `model`: `{model_type: "conv_attention", model_size: "small"|"medium"|"large"}`
- `steps`, `learning_rate`, `weight_decay`, `label_smoothing`, `max_negative_weight`, `target_fp_per_hour` (float)
- `batch_n_per_class`: `{positive, adversarial_negative, ACAV100M_sample, background_noise}`
- `custom_negative_phrases` ([str]) — phrase-specific, dropped by `train_batch.py` for auto-generated phrases

## Model registry schema (`models/wake/models.json`)

Managed by `training/manifest.py`, keyed by model slug (e.g. `"calcifer"`):

```json
{
  "calcifer": {
    "phrase": "<str>",
    "model_path": "<str, relative path>",
    "fpph": "<float, false positives/hour>",
    "recall": "<float>",
    "threshold": "<float>",
    "gate_passed": "<bool>",
    "trained_at": "<ISO8601 str>"
  }
}
```

Sourced from livekit's `eval.json` (`{optimal_fpph, optimal_recall, optimal_threshold}`) at training time via `manifest.py cmd_upsert`.

## Open Questions

- No Pydantic model source is on disk to confirm field types/validators/defaults precisely — the schema above is inferred from YAML values and inline comments, not from class definitions.
- Unclear whether `models/piper/*.onnx` (TTS voice) is meant to be pre-populated or downloaded on first run — it's referenced but not tracked.
