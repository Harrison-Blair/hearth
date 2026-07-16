---
id: PLM-003
title: Turn Metrics Logging
status: hatched
priority: P1
authored: 2026-07-15T23:44:08Z
agent: fledge-orchestrate/planning
fledge_version: 0.5.5
---

# PLM-003: Turn Metrics Logging

## Context
`hearth run` currently logs almost nothing about what a turn cost in tokens or
time: `hearth/brain/openai_compat.py::_OpenAICompatBackend.complete()` (shared
by both the local Ollama-style backend and the OpenRouter-style remote
backend) parses `choices[0].message` from the chat-completion response but
never reads `body["usage"]`, and no wall-clock timing is measured anywhere in
the request path. The user wants visible, after-the-fact debug output for
every model response — token counts, timing, throughput, and other
diagnostics — for both backend types the runtime supports (Ollama-style
`default` tier and OpenAI-compatible `tool` tier / OpenRouter), so they can
see what a turn is actually doing without instrumenting anything themselves.

A single user-facing turn (`Loop.run_turn`) can involve more than one LLM
call: the orchestrator's own ReAct rounds on the `default` tier, plus — if
`consult_brain` fires — a nested set of ReAct rounds on the `tool` tier
(`hearth/tools/consult.py`). Both call sites share one ReAct engine,
`run_react_rounds` in `hearth/loop.py`. This plumage logs metrics at two
granularities: immediately after each individual LLM call, and as an
aggregate summary at the end of each user-facing turn (including whatever
happened inside a nested consult).

## User Stories
- As the developer running `hearth run` locally, I want a log line after
  every model response showing input/output/thinking token counts, timing,
  and tokens/sec, so that I can see what each call actually cost without
  adding my own instrumentation.
- As the developer running `hearth run` locally, I want a per-turn summary
  line that aggregates every LLM call made during that turn (including any
  nested `consult_brain` calls), so that I can see the total cost of a turn
  at a glance instead of mentally summing per-call lines.
- As the developer running `hearth run` locally, I want this to work
  identically whether the call went to the local Ollama-style backend or the
  OpenAI-compatible remote (OpenRouter) backend, so that I don't lose
  visibility depending on which tier handled the turn.
- As the developer running `hearth run` locally, I want a clear marker when a
  call fails or times out (instead of a metrics line silently not
  appearing), so that I can tell a slow/expensive turn apart from a broken
  one.

## Functional Criteria
1. FC-1: After every LLM call returns successfully (from either the local or
   remote backend), a log line is emitted containing: which tier and model
   served it, which ReAct round it occurred in, input token count, output
   token count, thinking/reasoning token count when the backend reports one,
   call duration, and tokens/sec.
2. FC-2: Thinking/reasoning tokens are parsed from the OpenAI-compatible
   response's `usage.completion_tokens_details.reasoning_tokens` field when
   present; the per-call log line always shows a `thinking=` value, printing
   the literal `n/a` when the backend/model didn't report one (never `0`,
   which would misleadingly imply zero reasoning rather than "not
   reported").
3. FC-3: At the end of every user-facing turn (`Loop.run_turn`), one summary
   log line is emitted showing: the turn's 1-based sequential number within
   its session (derived from prior `final_answer` events for that
   `session_id`), the total number of ReAct rounds the turn took
   (orchestrator rounds plus any nested consult rounds), the number of LLM
   calls made (and how many of those failed), total input/output tokens
   across all calls in the turn, total wall-clock time for the turn, and a
   blended tokens/sec figure.
4. FC-4: The per-turn aggregate includes every LLM call made during the
   turn, including calls made inside a nested `consult_brain` invocation on
   the `tool` tier — a turn's numbers are never partial because part of the
   work happened in a nested consult.
5. FC-5: When an LLM call fails (raises `BrainError`) or the turn times out
   (`asyncio.TimeoutError`), a distinct one-line failure marker is logged in
   place of the normal per-call metrics line, showing tier, round, the
   client-safe `BrainError.reason` (or a timeout indicator), and the
   wall-clock time elapsed up to the failure. A failed call contributes to
   the turn's call count and total wall time but is excluded from the
   turn's token/tokens-per-second aggregate math (it produced no tokens).
6. FC-6: All metrics logging in this plumage works identically for both
   supported backend types (local Ollama-style `default` tier and OpenAI-
   compatible remote `tool` tier / OpenRouter) via the single shared
   `_OpenAICompatBackend.complete()` implementation both backends build on —
   no per-backend-type special-casing.
7. FC-7: Metrics lines are logged at `INFO` level on hearth's existing
   logging setup (`hearth/logging_setup.py`), visible by default under the
   existing `logging.level: INFO` default in `config.yaml` — no new config
   field or toggle is introduced to gate this behavior on or off.

## Acceptance Criteria
- [ ] AC-1: A per-call log line is emitted after every successful LLM
      completion (both local and remote backends), showing tier, model,
      ReAct round number, input tokens, output tokens, thinking tokens (or
      `n/a`), call duration, and tokens/sec — verified with a test that
      asserts on the emitted log record's content for each backend type.
- [ ] AC-2: A per-turn summary log line is emitted once per `Loop.run_turn`
      call, showing the session-sequential turn number, total ReAct round
      count, call count (with failure count when applicable), total
      input/output tokens, total turn wall-clock time, and blended
      tokens/sec — verified with a test asserting on the emitted summary
      for both a single-call turn and a turn that triggers a nested
      `consult_brain` call.
- [ ] AC-3: The per-turn aggregate correctly includes tokens/timing from
      calls made inside a nested `consult_brain` invocation, not just the
      orchestrator's own calls — verified with a test that exercises a turn
      including a `consult_brain` round and asserts the aggregate reflects
      both tiers' calls.
- [ ] AC-4: A failed or timed-out LLM call produces a distinct FAILED-style
      log marker (not a normal metrics line and not silence), is excluded
      from the turn's token/tokens-per-second math, but is included in the
      turn's call count and wall-clock time — verified with a test that
      forces a `BrainError` and a test that forces a turn timeout.
- [ ] AC-5: Thinking/reasoning tokens print as a numeric value when the
      backend response includes `usage.completion_tokens_details.reasoning_tokens`,
      and print the literal `n/a` when it is absent — verified with tests
      covering both a response with and without that field.
- [ ] AC-6: No metrics data introduced by this plumage crosses the veneer
      WebSocket wire — `hearth/veneer/protocol.py::serialize`'s existing
      whitelist and its `forbidden_keys` test coverage are unaffected;
      verified by confirming the existing wire-protocol tests still pass
      unmodified.

## Out of Scope
- Dollar cost computation. Neither backend's response reliably supplies a
  price (Ollama has none; OpenRouter's `usage.cost` is an opt-in extension
  not guaranteed present), and no config-driven price table is introduced in
  this plumage. Token counts captured here are the substrate a future
  feather could use to compute cost.
- Any change to the veneer wire protocol or `protocol.py::serialize`'s
  whitelist — these metrics are server-side log output only (console/file
  via the existing logging handlers), never sent to a connected WebSocket
  client.
- Any new configuration field or toggle to enable/disable metrics logging
  independently of the existing `logging.level` setting.
- Visual presentation of the new log lines (separators, ANSI colors,
  section styling) — tracked separately as the "Console Output Styling"
  plumage, which consumes the log lines this plumage produces.
- Native Ollama-API-only fields (e.g. `eval_count`, `total_duration` from
  Ollama's non-OpenAI-compatible `/api/chat` endpoint) — `hearth`'s
  `LocalBackend` talks to Ollama's OpenAI-compatible `/chat/completions`
  endpoint exclusively (`hearth/brain/local.py`), so only fields available
  on that shared response shape are used; timing is measured locally via
  wall-clock bracketing instead.

## Open Questions
None — resolved during interrogation.
