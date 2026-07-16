---
id: FTHR-016
title: Console color formatter
plumage: PLM-004
status: fledged
priority: P2
depends_on: []
authored: 2026-07-16T00:17:37Z
agent: fledge-orchestrate/planning
fledge_version: 0.5.5
---

# FTHR-016: Console color formatter

## Description
Build the generic console-styling mechanism as a tracer bullet: a
`logging.Formatter` subclass used only by the console `StreamHandler` that
(1) joins a line's fields with a single consistent ` │ ` delimiter, (2)
colors the timestamp and level segments by the record's log level with the
error color reserved exclusively for `ERROR`/`CRITICAL`, (3) reads an
optional `record.category` (set via `extra={"category": "..."}` at the log
call site) and applies that category's field-coloring rules when present,
falling back to plain timestamp+level coloring for uncategorized records
(including every third-party logger, e.g. `websockets`), and (4)
auto-suppresses all color (falling back to the plain delimited format) when
`sys.stdout` is not a TTY or `NO_COLOR` is set to a non-empty value. This
feather proves the whole mechanism using synthetic log records — no other
feather's log call sites need to exist yet for this one to be complete and
tested.

## Affected Modules
- `hearth/logging_setup.py` — `setup_logging()` (see
  `.fledge/nest/conventions.md` → "Logging": root + `websockets` logger
  configured once, idempotent marker, rotating file handler + optional
  console handler). This feather adds a new formatter class used **only**
  by the console `StreamHandler` this function already constructs; the
  rotating file handler keeps its existing plain `logging.Formatter`
  untouched.
- No other module changes — this feather is confined to the formatter
  itself; category tagging at real call sites is FTHR-016/017/018.

## Approach
1. Add a `ColorFormatter(logging.Formatter)` class in `hearth/logging_setup.py`
   (or a small sibling module if that keeps the file readable — engineer's
   call, no new package needed).
2. **Delimiter**: build each record's rendered line as fields joined by
   ` │ ` (space, U+2502, space) — at minimum `timestamp`, `levelname`, and
   the record's message; category-specific formatting (below) may further
   split the message on `key=value`-style segments the category defines,
   still joined with the same delimiter.
3. **Level coloring**: map `record.levelno` to an ANSI color/style
   (suggested: DEBUG dim gray, INFO default/no color, WARNING yellow,
   ERROR/CRITICAL bold red) applied to the timestamp+level segment. The
   ERROR/CRITICAL color must not be reused by any other level or by any
   category's field coloring — this is the hard "errors never blend in"
   requirement (PLM-004 FC-2), so pick the rest of the palette to avoid it
   entirely (e.g. don't use red anywhere else).
4. **Category dispatch**: read `category = getattr(record, "category", None)`.
   Define a small internal registry (e.g. a dict from category name to a
   coloring function/rule) that other feathers extend when they tag real
   call sites (FTHR-016 adds `"metrics"`, FTHR-017 adds `"connection"`,
   FTHR-018 adds `"server"`). When `category` is `None` or not in the
   registry, apply only the universal timestamp+level coloring with no
   further per-field treatment — this is the fallback every third-party
   logger (and any untagged hearth call) gets.
5. **TTY/NO_COLOR suppression**: at formatter-construction or per-format-call
   time, check `sys.stdout.isatty()` and `os.environ.get("NO_COLOR")`; when
   suppressed, emit the same field content and delimiter but with no ANSI
   codes at all (not even a "reset" code, since none was ever opened).
6. Wire the new formatter into `setup_logging()`'s console handler
   construction only (`if config.console:` branch) — the file handler's
   `formatter = logging.Formatter(...)` stays exactly as it is today.
7. Keep the registry/category-rule mechanism simple and file-local (a
   module-level dict is fine) — this feather only needs to prove the
   mechanism works, not anticipate every future category's exact colors.

## Tests
Written test-first — run against the unchanged (pre-FTHR-016) code first
and confirm failure (the formatter/class doesn't exist yet), then implement
until passing. New tests likely land in `tests/test_logging.py` (existing
file, see `.fledge/nest/testing.md` → FTHR-011 coverage) or a new
`tests/test_console_formatter.py`.
- `test_delimiter_present_in_every_line`: format a plain record and a
  record with `extra={"category": "metrics"}`; assert both contain ` │ `
  between their fields.
- `test_error_color_is_exclusive`: format one record per level
  (DEBUG/INFO/WARNING/ERROR/CRITICAL) and one record per registered
  category, with color forced on (mock `sys.stdout.isatty()` to `True`,
  clear `NO_COLOR`); collect every ANSI color code used across all of them
  and assert the ERROR/CRITICAL code appears in exactly those two outputs
  and nowhere else.
- `test_unknown_category_falls_back_to_level_only`: format a record with
  `extra={"category": "not-a-real-category"}` and a record with no
  `category` at all; assert both receive identical treatment (universal
  timestamp+level coloring only, no category-specific rule applied) —
  this also stands in for "a third-party logger's record", since
  `websockets`' records never carry a `category` attribute.
- `test_no_color_when_not_a_tty`: mock `sys.stdout.isatty()` to `False`,
  format a record, and assert the output contains no ANSI escape
  sequences (`\x1b[`) while still containing the ` │ ` delimiter and full
  content.
- `test_no_color_when_no_color_env_set`: with `sys.stdout.isatty()` mocked
  `True`, set `NO_COLOR=1` in the test's environment and assert no ANSI
  codes appear.
- `test_file_handler_unaffected`: call `setup_logging()` with `console=True`
  and inspect the file handler's formatter/output directly — assert it is
  unchanged from today's plain `logging.Formatter` output (no delimiter
  insertion, no ANSI codes), proving the new formatter is console-only.

## Acceptance Criteria
- [x] AC-1: The tests listed above were observed failing before implementation and pass after.
- [x] AC-2: Every console-handler-formatted line contains the ` │ ` delimiter between its fields, for both categorized and uncategorized records. Satisfies PLM-004 FC-1; PLM-004 AC-1.
- [x] AC-3: `ERROR`/`CRITICAL` records are colored with an ANSI code used by no other level and no category's field coloring, verified across every level and every registered category. Satisfies PLM-004 FC-2; PLM-004 AC-2.
- [x] AC-4: A record's `extra={"category": ...}` value selects that category's coloring rule when registered; an unregistered or absent category falls back to universal timestamp+level coloring only, identically to how a third-party (e.g. `websockets`) record is treated. Satisfies PLM-004 FC-3; PLM-004 AC-3 (partial — full AC-3 coverage across metrics/connection/server completes once FTHR-016/017/018 register those categories).
- [x] AC-5: No ANSI escape codes appear in console output when `sys.stdout.isatty()` is false or `NO_COLOR` is set to a non-empty value; the delimiter and content are unaffected in both cases. Satisfies PLM-004 FC-7; PLM-004 AC-4.
- [x] AC-6: The rotating file handler's formatter and output are unchanged by this feather. Satisfies PLM-004 FC-8; PLM-004 AC-5.
