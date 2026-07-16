---
id: PLM-004
title: Console Output Styling
status: hatched
priority: P2
authored: 2026-07-16T00:03:59Z
agent: fledge-orchestrate/planning
fledge_version: 0.5.5
---

# PLM-004: Console Output Styling

## Context
`hearth run`'s console output (the daemon's log stream via
`hearth/logging_setup.py`'s optional console `StreamHandler`) is currently a
flat, undifferentiated stream of plain-text log lines from multiple loggers
(`hearth.loop`, `hearth.brain.openai_compat`, `websockets`, etc.), all at the
same visual weight. PLM-003 adds a substantial amount of new information to
this stream (per-call and per-turn debug metrics, plus FAILED/timeout
markers). This plumage makes that console output visually scannable: an
in-line field delimiter for quick navigation within a line, and
multi-dimensional coloring (timestamp, log level, and message category) so
different kinds of output are distinguishable at a glance — with the hard
requirement that an error can never be visually confused with a non-error.

This plumage is scoped to the `hearth run` daemon's own console log stream
only — not the separate `python -m hearth.veneer.client` companion CLI
program, which already has its own unrelated, unrequested ad hoc coloring.
It depends on PLM-003 (specifically FTHR-013 and FTHR-014) for the metrics
category's log lines to exist and to be tagged/leveled the way this plumage's
coloring rules expect (FTHR-014's FAILED/timeout markers were amended during
interrogation to log at `WARNING` level specifically so they inherit
error-adjacent coloring under this plumage's level-based rules).

## User Stories
- As the developer running `hearth run` locally, I want each console log
  line to have clearly delimited fields, so that I can quickly scan to the
  start or end of any field within a busy line (e.g. a metrics line with
  many `key=value` segments).
- As the developer running `hearth run` locally, I want different kinds of
  output — token-usage metrics, connection lifecycle, server startup,
  errors — to be visually distinguishable by color, so that I can tell at a
  glance what kind of thing I'm looking at without reading every word.
- As the developer running `hearth run` locally, I want an error to never
  be colored the same as anything else, so that a real problem can never be
  mistaken for routine output while I'm scanning the console.
- As the developer running `hearth run` locally, I want colors to
  automatically disappear when I redirect or pipe the output (or set
  `NO_COLOR`), so that redirected logs and files never get garbled with raw
  escape codes.

## Functional Criteria
1. FC-1: Every console log line emitted by `hearth run`'s console handler
   uses a single, consistent in-line delimiter (` │ `, a space-padded
   vertical bar) between its fields/segments, applied uniformly regardless
   of category.
2. FC-2: Every console log line's timestamp and log-level segments are
   colored based on the record's log level (`DEBUG`/`INFO`/`WARNING`/
   `ERROR`/`CRITICAL`), and `ERROR`/`CRITICAL` use a color used by no other
   level or category — an error can never share a color with non-error
   output.
3. FC-3: Log calls in `hearth`'s own code can opt into a message
   `category` (e.g. `metrics`, `connection`, `server`) by passing
   `extra={"category": "..."}`; the console formatter reads this and
   applies that category's field-coloring rules (potentially coloring
   individual `key=value` segments differently within the category, not
   just the whole line one color). Log records with no `category` (the
   default — including every third-party logger we don't control, e.g.
   `websockets`) fall back to the universal timestamp+level coloring only,
   never a category's bespoke rules.
4. FC-4: The `metrics` category covers PLM-003's per-call and per-turn log
   lines (`hearth/loop.py`, `hearth/brain/openai_compat.py`) and FTHR-014's
   FAILED/timeout markers.
5. FC-5: The `connection` category covers hearth's own connection-lifecycle
   log points in `hearth/veneer/server.py` (e.g. a client connecting,
   disconnecting, or a malformed-frame rejection) — not `websockets`'
   internal connection logging, which this plumage cannot tag.
6. FC-6: The `server` category covers the daemon startup/lifecycle log
   points in `hearth/app.py`'s `_run_daemon()`.
7. FC-7: Color is emitted only when `sys.stdout.isatty()` is true and the
   `NO_COLOR` environment variable is unset or empty; otherwise every line
   falls back to the plain, uncolored format (still using the FC-1
   delimiter, since it is plain text, not an ANSI code). No new
   configuration field controls this — it is fully automatic.
8. FC-8: Colorization applies only to the console `StreamHandler`; the
   rotating file handler and per-session transcripts (`hearth/transcript.py`)
   remain plain text, unaffected by this plumage.

## Acceptance Criteria
- [ ] AC-1: Every line the console handler emits contains the ` │ ` delimiter
      between its logical fields, verified with a test that captures
      console output (with color disabled, e.g. non-TTY) and asserts the
      delimiter's presence/positioning for a representative line from each
      category plus an untagged line.
- [ ] AC-2: On a TTY with `NO_COLOR` unset, `ERROR`/`CRITICAL` lines are
      wrapped in an ANSI color code that no `DEBUG`/`INFO`/`WARNING` line or
      any category ever uses, verified with a test asserting the full set
      of colors used across levels/categories has no overlap with the
      error color.
- [ ] AC-3: A log call with `extra={"category": "metrics"}` (and similarly
      `"connection"`, `"server"`) is rendered with that category's
      field-coloring rules; a log call with no `category` extra (including
      a simulated third-party-style log record) renders with only
      timestamp+level coloring and no category-specific rule — verified
      with tests covering all three categories plus the uncategorized
      fallback.
- [ ] AC-4: With `sys.stdout.isatty()` false, or `NO_COLOR` set to a
      non-empty value, no ANSI escape codes appear anywhere in the
      formatted output (delimiter and content unaffected) — verified with
      tests covering both suppression conditions independently.
- [ ] AC-5: The rotating file handler's output is unaffected by this
      plumage (no ANSI codes, no forced delimiter change beyond what
      already exists) — verified by a test asserting file-handler output is
      unchanged for a line that the console handler renders with color and
      a delimiter.

## Out of Scope
- The separate `python -m hearth.veneer.client` companion CLI's own
  `print()`-based output — untouched; it already has its own unrelated,
  pre-existing hardcoded ANSI color that this plumage does not alter.
- Bespoke per-category coloring for log lines from loggers this codebase
  doesn't author (e.g. `websockets`' internal logging) — those get the
  universal timestamp+level coloring only, never a category tag, since
  reliable tagging requires touching the call site and pattern-matching
  third-party text is explicitly rejected as fragile.
- Any new `logging.*` configuration field (e.g. an explicit color on/off
  toggle) — color behavior is fully automatic via TTY-detection and the
  `NO_COLOR` environment variable convention.
- Any change to the rotating file handler's or per-session transcripts'
  output format — colorization is console-`StreamHandler`-only; file-based
  output stays exactly as produced today (plus whatever PLM-003 adds to its
  content, which is a separate plumage's concern).
- Additional categories beyond `metrics`/`connection`/`server` (e.g. a
  per-tool-call category, a per-session category) — not requested during
  interrogation; can be added as thin follow-on feathers reusing this
  plumage's tagging mechanism if wanted later.

## Open Questions
None — resolved during interrogation.
