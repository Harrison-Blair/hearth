---
id: FTHR-011
title: Logging infra plus dual-model logging and per-session transcript
plumage: PLM-002
status: hatching
priority: P1
depends_on: [FTHR-009]
authored: 2026-07-11T02:52:26Z
agent: fledge-orchestrate/planning
fledge_version: 0.3.4
---

# FTHR-011: Logging infra plus dual-model logging and per-session transcript

## Description
`LoggingConfig` (`hearth/config.py`) currently exists (`level`, `dir`) but nothing calls `logging.basicConfig`/attaches a handler anywhere in `hearth/` — there is no rotating file log, and the `websockets` library's own logger falls through to Python's unconfigured root logger, which is why a client disconnect currently dumps a raw keepalive traceback to stderr. This feather wires real logging: a `RotatingFileHandler` configured once at daemon startup from `LoggingConfig`, routing both hearth's own logging and the `websockets` logger to file; plus a per-session human-readable transcript. Because FTHR-009 splits every turn into an orchestrator (local) leg and, optionally, one or more brain-consult (remote) legs, this feather's dual-model requirement means both legs must be identifiable in the log/transcript output, not just whichever model answered last.

## Affected Modules
- New `hearth/logging_setup.py` — `setup_logging(config: LoggingConfig) -> None`: builds a `logging.handlers.RotatingFileHandler` from `config.dir`/`file_name`/`max_bytes`/`backup_count`, attaches it (with a level from `config.level`) to the root logger *and* explicitly to the `"websockets"` logger (so its keepalive/connection-close messages go to the file, not stderr). Idempotent — calling it more than once (e.g. across tests) does not stack duplicate handlers on the root logger.
- New `hearth/transcript.py` — `Transcript(transcript_dir: str)`: `append(session_id, line: str) -> None` appends a timestamped line to `<transcript_dir>/<session_id>.txt` (created on first write), best-effort (a write failure is caught and swallowed, never raised into the turn).
- `hearth/config.py:91-94` (`LoggingConfig`) — add `file_name: str = "hearth.log"`, `max_bytes: int = 1_000_000`, `backup_count: int = 5`, `transcript_enabled: bool = True`, `transcript_dir: str = "logs/transcripts"`; keep `level`, `dir`.
- `hearth/app.py` — call `setup_logging(settings.logging)` once, early in `_run_daemon`, before constructing the router/loop/veneer; construct a `Transcript` (when `transcript_enabled`) and pass it into `Loop`.
- `hearth/loop.py` (`Loop.run_turn`, extended by FTHR-009) — log a record identifying the orchestrator's local model/backend at the start of the turn (via the standard `logging` module, not the sqlite `EventLog`, which already has `routing_decision`); when `transcript` is configured, write the user text and, at the end, the final answer to the session's transcript file, in order.
- `hearth/tools/consult.py` (`BrainConsult.__call__`, added by FTHR-009) — log a record identifying the consult's remote model/backend; when a transcript is wired in (passed down from `Loop` or injected at construction), write the consult query and its findings to the same session's transcript file, positioned between the surrounding turn's user/answer lines.
- `config.yaml` / `default-config.yaml` — mirror the new `logging.*` fields with inline doc comments.
- New `tests/test_logging.py`.

## Approach
- `setup_logging` is a plain function, called exactly once from `app.py`'s `_run_daemon` (and separately, per-test, inside `tests/test_logging.py` against a `tmp_path`-scoped `LoggingConfig`) — no import-time `basicConfig` anywhere, so importing `hearth.*` modules in tests never has a logging side effect. Guard idempotency by checking for a marker attribute/handler already present on the root logger before adding another.
- The sqlite `EventLog` stays the structured store of record (unchanged by this feather) — `logging_setup`/`transcript` are additive, human-facing surfaces layered on top, not a replacement.
- "Both models logged" is satisfied structurally by logging at the two seams FTHR-009 already created: `Loop.run_turn` knows the orchestrator's `selection.backend_name`/`tier`, and `BrainConsult.__call__` knows the consult's `selection.backend_name`/`tier` — each logs its own model identity at its own call site, so a turn with a consult naturally produces two distinct model-identifying log records.
- `Transcript.append` is deliberately dumb (append a line, create-if-missing) — ordering within one turn falls out of call order (`Loop` writes the user line first, then awaits any consults which write their own lines as they complete, then `Loop` writes the final answer line last).
- Logging/transcript calls in `Loop`/`BrainConsult` are wrapped so a failure (disk full, permission error) is caught and logged-if-possible but never propagates into the turn — this is what AC-5 pins down.

## Tests
Written test-first in `tests/test_logging.py` (new), using `tmp_path` for both the log dir and transcript dir, and FTHR-009's `two_tier_llm_config` fixture for a consult-driving turn:
- `test_setup_logging_creates_rotating_handler` — call `setup_logging` with a `LoggingConfig` pointed at `tmp_path`; assert a `RotatingFileHandler` is attached with the configured `max_bytes`/`backup_count`, and a logged message actually lands in the file.
- `test_setup_logging_is_idempotent` — call `setup_logging` twice; assert the root logger doesn't accumulate duplicate handlers.
- `test_websockets_logger_routed_to_file` — after `setup_logging`, a message logged via `logging.getLogger("websockets")` lands in the same file (not just the root logger's default stderr handler).
- `test_consult_turn_logs_both_models` — drive a full orchestrator turn that triggers one `consult_brain` call; assert the log file (or captured log records, via `caplog`) contains an identifying record for the local backend/model and a separate one for the remote backend/model.
- `test_transcript_contains_ordered_turn_lines` — with `transcript_enabled=True`, drive a consult-triggering turn; read `<transcript_dir>/<session_id>.txt` and assert it contains the user text, the consult query, the consult findings, and the final answer, in that order.
- `test_logging_failure_does_not_crash_turn` — inject a `Transcript`/logger that raises on write; drive a turn; assert `run_turn` still returns a normal answer (doesn't propagate the write failure).

Implementation order: write the above against the unchanged code (no `logging_setup.py`/`transcript.py` exist yet — import errors are the expected first failure), then implement until green.

## Acceptance Criteria
- [ ] AC-1: The tests listed above were observed failing before implementation (import errors on the not-yet-existing modules, or missing log/transcript output) and pass after.
- [ ] AC-2: A `RotatingFileHandler` is configured from `LoggingConfig` (`file_name`/`max_bytes`/`backup_count`/`dir`) at daemon start; setup is idempotent and configured only in `app.py`/tests (no import-time/`basicConfig` side effect). Satisfies PLM-002 FC-7.
- [ ] AC-3: A consult turn logs records naming **both** the orchestrator model (`qwen3:14b`/local) **and** the consultation's remote model/backend. Satisfies PLM-002 FC-7.
- [ ] AC-4: With `transcript_enabled`, a per-session file under `transcript_dir` contains the user text, final answer, and each consult query/findings, in order. Satisfies PLM-002 FC-8.
- [ ] AC-5: Logging/transcript failures never crash a turn — a forced write failure still produces a normal returned answer.
