---
id: FTHR-005
title: Layer-2 read seam and no-op consumer
plumage: PLM-001
status: egg
priority: P0
depends_on: [FTHR-002]
oversight: merge
authored: 2026-07-11T00:15:30Z
agent: fledge-orchestrate/planning
fledge_version: 0.3.0
---

# FTHR-005: Layer-2 read seam and no-op consumer

## Description
Define — but do not build — the Layer-2 memory seam: a read-side, pull-based interface over the event log that a future background indexer (Graphiti/FalkorDB, later phase) attaches to, plus a no-op consumer stub proving the seam. The synchronous write path (FTHR-002) stays uncoupled from and unaffected by any consumer. Read-side only: this feather does not touch the loop, veneer, or app wiring, keeping it conflict-free with the rest of the wave.

## Affected Modules
- `hearth/memory/reader.py` — `EventReader`.
- `hearth/memory/consumer.py` — `Layer2Consumer` protocol + `NoOpConsumer`.
- `tests/test_layer2_reader.py`.
- (Builds on `hearth/memory/log.py` from FTHR-002; see `.fledge/nest/architecture.md` → "Layer-2 seam" intent.)

## Approach
- **`EventReader(log_or_db)`**: `read_since(cursor: int, limit: int) -> list[Event]` returns events with `id > cursor` in ascending `id` order (the `id` is the cursor); `latest_cursor() -> int` returns the max `id` (0 when empty). Read-only — no writes, no coupling to the writer. Reuses the `Event` shape and SQLite table from FTHR-002.
- **`consumer.py`**: `Layer2Consumer` is a typed protocol (`async def consume(self, events: list[Event]) -> None`). `NoOpConsumer` implements it and does nothing. A helper `pull_once(reader, consumer, cursor) -> new_cursor` demonstrates a poll step (read_since → consume → advance cursor) without any scheduler. Phase 0 wires the stub only as an available, tested seam — it is deliberately NOT started inside the daemon (that, and a real indexer, are a later phase), which is what keeps this feather off `app.py`.
- **Uncoupling guarantee**: `EventLog.append` (FTHR-002) is unchanged and has no reference to readers or consumers; a test asserts appends succeed and are fully readable whether or not a consumer exists or has run.

## Tests
Written test-first (write → observe FAIL → implement to green). `tests/test_layer2_reader.py`; hermetic (in-memory/temp SQLite); `pytest`/`asyncio_mode=auto`:
- `test_read_since_cursor_ordered` — appending N events then `read_since(k)` returns exactly the events with `id > k`, in ascending order; `latest_cursor()` tracks the max id. (AC-2)
- `test_noop_consumer_pulls_events` — `pull_once` with a `NoOpConsumer` reads appended events and advances the cursor; a spy consumer confirms it received them in order. (AC-3)
- `test_write_path_unaffected_without_consumer` — appends succeed and are readable with no consumer attached and none ever run; `append` exposes no consumer/reader coupling. (AC-4)

## Acceptance Criteria
- [ ] AC-1: The tests listed above were observed failing before implementation and pass after.
- [ ] AC-2: A read-side, cursor-based, ordered pull interface over the event log exists and is typed (satisfies PLM-001 FC-13).
- [ ] AC-3: A no-op consumer stub implements the Layer-2 consumer protocol and can pull appended events by cursor (satisfies PLM-001 FC-13, contributes to PLM AC-5).
- [ ] AC-4: The synchronous write path is uncoupled from and unaffected by any consumer's presence, absence, or speed (satisfies PLM-001 FC-13).
