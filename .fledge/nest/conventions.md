---
generated: 2026-07-15T23:27:05Z
commit: e41ba8a73a56364e7c3bb1acf1332cadab817e45
agent: fledge-forager
fledge_version: 0.5.5
---

# Conventions

Naming, error handling, layering, and idioms observed across `hearth/`, tests, and the training pipeline — reconciled where scouts overlapped.

## Config and secrets

- **Layered config:** `config.yaml` (base, gitignored is false — it's the active config) → `.env` secrets → `HEARTH_*` env vars (nested with double underscore, e.g. `HEARTH_LLM__MODEL`) → `HEARTH_CONFIG` explicit override path. Implemented via `pydantic-settings` custom `settings_customise_sources` (`hearth/config.py`).
- **Hard rule (FTHR-015):** API keys live only in `.env` (`HEARTH_<SECTION>__<PROVIDER>_API_KEY`), never in YAML. `LLMBackend.resolve_api_key()` reads `os.environ` at call time. No schema validation currently blocks a stray key field in YAML (open question, see `architecture.md`).
- Every tunable (models, hosts, thresholds, timeouts) is config, never hardcoded — enables the Pi-5 port to be config-only.

## Error handling

- `hearth/brain/errors.py::BrainError(reason, detail)` — `reason` is client-safe (shown to the user / logged to wire-safe channels), `detail` is internal-only (status code, raw body). Backends catch `httpx` exceptions and normalize to `BrainError`; a `curate_error`-style whitelist checks exception type before extracting a message.
- Retry policy: only transient `httpx.TransportError` is retried (`max_retries` per backend config); timeouts and `HTTPStatusError` are never retried.
- `BrainConsult` degrades `BrainError`/timeout to a plain-text observation rather than raising — the orchestrator always gets *something* back from a nested consult.
- Tool-activity emission is balanced (start/end) even under timeout: the ReAct loop uses a `finally` block, and `asyncio.CancelledError` (a `BaseException`) is never accidentally swallowed by an inner `except Exception`.

## Wire/boundary discipline

- `hearth/veneer/protocol.py::serialize` is a structural whitelist — only `type`/`turn_id`/`phase`/`label`/`text` may cross the wire; anything else (tool query, arguments, observation, result) raises rather than silently drops. Tests enforce this with an explicit `forbidden_keys` set.
- `hearth/memory/log.py::EventLog` exposes only `append` and `read_session` — no update/delete, ever. `EventReader` is a separate read-only type; writers are never coupled to it.

## Async and concurrency

- Async/await throughout for all I/O (`httpx`, `websockets`, sqlite, file writes).
- `asyncio.wait_for` enforces `turn_timeout_s` / `consult_timeout_s`; `asyncio.to_thread` offloads blocking stdin reads in `veneer/client.py`.
- Session ID: one `uuid4` per WebSocket connection; turn_id comes from the client per request; event-log entries and history reconstruction are both keyed on `(session_id, turn_id)`.
- `websockets.serve(..., ping_interval=None)` — deliberate: idle localhost control-surface connections shouldn't false-close; dead-peer detection instead relies on `send()` raising `ConnectionClosed`.

## No-op stubs / seams left for future feathers

- `hearth/persona.py::restyle` returns text unchanged (FTHR-011 placeholder for a future restyle stage).
- `hearth/tools/__init__.py` is an empty seam; `ToolRegistry` returns an empty tool list when unconfigured rather than erroring.
- `hearth/memory/consumer.py::NoOpConsumer` is a reference no-op implementation of the Layer-2 consumer interface.

## Logging

- Root + `websockets` logger configured exactly once at daemon start, guarded by an idempotent marker attribute (safe to call `logging_setup` more than once, e.g. in tests).
- Rotating file handler (`max_bytes`, `backup_count` from config) + optional console handler; never configured at import time.
- Per-session transcripts are best-effort — `OSError` is swallowed so transcript/logging failures never crash a turn.

## Testing idioms

See `testing.md` for the full breakdown; conventions worth calling out here because they recur repo-wide:
- `httpx.MockTransport` + a `HostRouter` fixture that branches by request host, for deterministic multi-backend assertions.
- Fake/duck-typed config objects (`_Config`, `_Conversation`, etc.) with only the attributes a test needs, avoiding full `Settings` load.
- `async def test_*()` with no `@pytest.mark.asyncio` — `asyncio_mode=auto` in `pyproject.toml`.

## Training-pipeline conventions (`training/`)

- Strict venv isolation: `training/.venv-train` never shares packages with the runtime venv; the runtime is meant to consume only the exported `.onnx`.
- `manifest.py` is deliberately stdlib-only (no `hearth` imports) — invokes `train.py` via `subprocess`, hand-parses/round-trips YAML when editing `config.yaml`.
- Config layering: base template (`calcifer.yaml`) → smoke overrides → optional CLI sweep overrides (`--n-samples`, `--steps`) → effective YAML written to `training/work/`.
- All heavy artifacts (`training/data`, `training/output`, `training/work`, `.venv-train`) are gitignored; only YAML configs and scripts are tracked.

## Naming

- **FTHR-xxx / PLM-xxx** — fledge's feature/epic identifiers, referenced directly in test coverage and commit messages (see `domain.md`).
- Slugification in `training/manifest.py`: lowercase, non-alphanumerics collapsed to underscores; the inverse "prettify" is lossy (casing/spacing not recoverable).

## Open Questions

- None beyond the FTHR-015 enforcement gap already carried into `architecture.md`.
