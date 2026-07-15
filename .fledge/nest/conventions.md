---
generated: 2026-07-15T22:30:28Z
commit: a8489b1afa55662a54ba66548a2e176584a3f387
agent: fledge-forager
fledge_version: 0.5.4
---

# Conventions

Coding, configuration, and process conventions observed across the repository, reconciled across modules.

## Configuration

- Two-file config model: `config.yaml` (active) + `default-config.yaml` (reference, one inline comment per field) — root.md, `CLAUDE.md`.
- Secrets rule (FTHR-015, hard rule): API keys live only in `.env` (`HEARTH_<SECTION>__<PROVIDER>_API_KEY`), never in YAML — root.md, hearth.md.
- Env var naming: `HEARTH_` prefix, `__` (double underscore) for nesting, e.g. `HEARTH_LLM__OPENROUTER_API_KEY`, `HEARTH_LOGGING__LEVEL` — root.md.
- Precedence, most to least specific: init kwargs > exported `HEARTH_*` env vars > `.env` > `config.yaml` > `default-config.yaml` fallback (`hearth/config.py:Settings.settings_customise_sources`) — hearth.md, root.md.
- `config.yaml` path resolution: `HEARTH_CONFIG` env var > package-adjacent (source checkout) > `./config.yaml`; fails loudly if none found — hearth.md, root.md.
- Secrets are resolved lazily via `api_key_env` → `os.environ` lookup at time of use, never stored on the `Settings` object itself — hearth.md.
- `training/manifest.py select` edits `config.yaml`'s `wake.model_paths` block with a regex-based in-place patch that preserves comments/ordering, not a full YAML rewrite/dump — training.md.

## Async & concurrency

- Async-first throughout `hearth/`: `async def`/`await` for all I/O, `asyncio.wait_for()` for timeouts, `async for` for websocket iteration — hearth.md.
- `EventSink` is an async callable (`Callable[[object], Awaitable[None]]`); no synchronous callback path — hearth.md.
- One turn in flight per WebSocket connection at a time (server awaits full turn completion before reading the next frame) — hearth.md.

## Error handling

- `BrainError(reason, detail)`: `reason` is client-safe/short, `detail` is internal-only diagnostic text — never includes Authorization headers or resolved API keys — hearth.md.
- HTTP/transport exceptions are curated at the boundary into specific `BrainError` reasons (e.g. `httpx.TimeoutException`/`TransportError` → "backend unreachable", `HTTPStatusError` → "backend error") — hearth.md.
- Malformed model output (`json.JSONDecodeError`, `KeyError`, `TypeError` while parsing tool calls) is caught and wrapped as `BrainError("unreadable response")` rather than propagating — hearth.md.
- Tool-call failures inside the ReAct loop become string observations (`"error: {exc}"`) fed back to the model — they never crash the loop — hearth.md.
- Graceful degradation is a repeated pattern (documented as "AC-5 pattern"): transcript writes and logging failures are caught and swallowed (`try/except: pass`) so a disk/logging issue never aborts a turn — hearth.md, root.md.
- Training's batch driver (`train_batch.py`) catches `subprocess.CalledProcessError` per phrase, records the failure, and continues the batch rather than aborting — training.md.

## Serialization / boundary discipline

- `hearth/veneer/protocol.py` enforces a strict whitelist: only `ToolActivity.phase`/`.label` cross the WebSocket wire — tool query text, arguments, and observation content never leave the process. Verified by `tests/test_veneer.py` ("tool activity opacity boundary") — hearth.md, tests.md.
- `parse_request()` validates JSON keys up front and rejects malformed frames without echoing their content back — hearth.md.

## Logging

- Idempotent logging setup guarded by a marker attribute on the root logger so repeated `setup_logging()` calls don't stack handlers — `RotatingFileHandler` + optional console — hearth.md.
- `websockets`' own logger is explicitly wired into the same setup so its output lands in the rotating file too — hearth.md.
- Dual-model logging: the orchestrator's backend selection and the nested consult's backend selection are logged distinctly ("orchestrator" vs "consult") — hearth.md.
- Per-session human-readable transcripts are written under `logging.transcript_dir`, one line per turn, best-effort — hearth.md, root.md.

## Isolation

- `training/.venv-train` (ROCm torch + livekit-wakeword) must **never** share packages with the runtime `.venv` — enforced by convention/docs, not tooling; only the exported `.onnx` artifact crosses — training.md, root.md, `CLAUDE.md`.
- `training/manifest.py` deliberately imports stdlib only, so it stays usable from the repo root without any training-venv dependency — training.md.
- `packaging/build.sh` builds its own isolated `.build-venv` for the PyInstaller build, separate from both the dev `.venv` and `training/.venv-train` — packaging.md.

## Naming / typing

- `@dataclass` for wire/protocol-shaped types (`Message`, `ToolCall`, `ToolSpec`, `BrainResult`, `Capabilities`, `Event`, `Request`, `Selection`); `Protocol` for structural interfaces (`Brain`, `Layer2Consumer`) — hearth.md.
- Config models use pydantic `BaseModel`/`BaseSettings`, distinct from the dataclass style used elsewhere — hearth.md.
- Test double classes are prefixed `_` (private): `_FakeLoop`, `_FakeRegistry`, `_Config`, `_Agent`, etc. — tests.md.
- Wake-model slugs are derived deterministically: phrase → lowercase → non-alphanumerics collapsed to `_` → stripped of leading/trailing `_` (`training/manifest.py:slug`); the inverse "prettify" is lossy (original casing not recoverable) — training.md.
- Bash scripts use `set -euo pipefail` (packaging/build.sh) — packaging.md.

## Testing conventions

See `testing.md` for the full picture; summary: pytest with `asyncio_mode=auto` (no `@pytest.mark.asyncio` needed), hermetic via `httpx.MockTransport` and websockets test doubles, an autouse fixture (`_reset_logging_state`) resets logging state between tests to avoid handler leakage — tests.md.

## Fledge process conventions

- `PLM-xxx` = epic ("plumage"), `FTHR-xxx` = child implementable unit ("feather") with numbered acceptance criteria (AC-1, AC-2, …) — `CLAUDE.md`, root.md.
- Test-first commits (`FTHR-xxx: test-first — … tests`), completion commits (`FTHR-xxx: fledged`), review commits (`review: verify FTHR-xxx AC-1..N`) — `CLAUDE.md`.
- `.fledge/` and `.fledgeignore` are working state/scan-exclusion, not source — regenerable, ignored by convention.

## Open Questions

- Is there an enforced (e.g. CI or lint) check for the "secrets only in `.env`" and "no venv sharing" rules, or are they convention-only? (root.md, hearth.md)
