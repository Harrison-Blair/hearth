---
id: FTHR-018
title: Connection category tagging
plumage: PLM-004
status: egg
priority: P2
depends_on: [FTHR-016]
authored: 2026-07-16T00:27:18Z
agent: fledge-orchestrate/planning
fledge_version: 0.5.5
---

# FTHR-018: Connection category tagging

## Description
Give hearth's own connection-lifecycle log points a `connection` category
so FTHR-016's console formatter colors them distinctly. `hearth/veneer/server.py`
today only logs a disconnect (`logger.info("client disconnected mid-turn...")`)
and a malformed-frame rejection (`logger.warning("rejecting malformed
request frame...")`) — there is no log line at all for a client connecting.
This feather adds one new, minimal `logger.info(...)` call at connection
acceptance (in `_handle_connection`, right after a `session_id` is
generated) and tags all three points (connect/disconnect/malformed-frame)
with `extra={"category": "connection"}`. Depends only on FTHR-016 (the
formatter/registry).

## Affected Modules
- `hearth/veneer/server.py` — `Veneer._handle_connection` (see
  `.fledge/nest/architecture.md` → "Key seams" / `hearth/veneer/`: "the
  localhost control surface"). Only hearth's own log calls in this file are
  touched; `websockets`' internal connection logging (e.g. its own
  handshake/close messages) is untouched and untagged — it falls back to
  FTHR-016's universal timestamp+level coloring, per PLM-004 FC-5's
  explicit carve-out.
- `hearth/logging_setup.py` — register the `connection` category's
  coloring rule in FTHR-016's registry.

## Approach
1. In `Veneer._handle_connection`, add one new `logger.info("client
   connected session=%s", session_id, extra={"category": "connection"})`
   (or equivalent) immediately after `session_id = uuid.uuid4().hex` — this
   is the first point in the method where a connection is known to exist,
   before any turn is processed.
2. Add `extra={"category": "connection"}` to the two existing log calls in
   this file: the disconnect `logger.info(...)` and the malformed-frame
   `logger.warning(...)`. Do not change either call's message text or level.
3. In `hearth/logging_setup.py`, register a `"connection"` entry in
   FTHR-016's category registry (a coloring treatment distinct from
   `metrics`/`server`/plain, and never reusing the ERROR/CRITICAL color —
   note the malformed-frame line is already `WARNING`-level and will get
   that level's color regardless of category, same as FTHR-016's universal
   rule; the category can still tint additional segments if the registry
   design supports per-segment rules within a leveled line).
4. No changes to `hearth/veneer/protocol.py`'s wire whitelist or any
   existing veneer test's assertions about wire message content — this
   feather only touches server-side `logger` calls, never anything sent to
   a WebSocket client.

## Tests
Written test-first — run against the code as it stands after FTHR-016
(before this feather's changes) and confirm failure (no connection-accepted
log line exists yet; existing disconnect/malformed-frame lines carry no
`category`), then implement until passing. Likely lands in `tests/test_veneer.py`
or `tests/test_veneer_errors.py` (see `.fledge/nest/testing.md` → FTHR-001
coverage row for existing veneer test files).
- `test_connection_accepted_is_logged`: open a connection to a test
  `Veneer` instance (or drive `_handle_connection` directly with a fake
  websocket, per existing `FakeWebSocket` conventions) and assert, via
  `caplog`, that a `category="connection"` INFO record is emitted before
  any turn is processed.
- `test_disconnect_and_malformed_frame_carry_category_tag`: reuse existing
  disconnect-mid-turn and malformed-frame test scenarios already covered in
  `test_veneer.py`/`test_veneer_errors.py`, and additionally assert each
  resulting `LogRecord` has `record.category == "connection"`.
- `test_connection_category_gets_registered_coloring` (extends
  `test_console_formatter.py`/`test_logging.py`): format a
  connection-shaped log record with `category="connection"` through the
  console formatter (color forced on) and assert it renders with a
  treatment distinct from `metrics`/`server`/plain and never the reserved
  ERROR/CRITICAL color.
- Regression check: existing `test_veneer.py` wire-whitelist assertions
  (`forbidden_keys`) and connection-handling behavior tests pass unmodified
  — this feather adds a log call and tags, nothing on the wire.

## Acceptance Criteria
- [x] AC-1: The tests listed above were observed failing before implementation and pass after.
- [x] AC-2: A new INFO log line is emitted when `Veneer._handle_connection` accepts a connection, tagged `extra={"category": "connection"}`, before any turn is processed. Satisfies PLM-004 FC-5.
- [x] AC-3: The existing disconnect and malformed-frame log calls in `hearth/veneer/server.py` carry `extra={"category": "connection"}` with unchanged message text and level. Satisfies PLM-004 FC-5.
- [x] AC-4: The console formatter's `connection` category renders these lines distinctly from `metrics`/`server`/plain and never reuses the reserved ERROR/CRITICAL color, completing PLM-004 AC-3's connection-category coverage.
- [x] AC-5: Existing `test_veneer.py`/`test_veneer_errors.py` wire-whitelist and connection-behavior tests pass unmodified.
