---
id: PLM-004
title: OpenRouter via a generic OpenAI-compatible LLM gateway
status: hatched
priority: P2
authored: 2026-07-07T23:05:24Z
agent: fledge-orchestrate/planning
fledge_version: 0.2.0
---

# PLM-004: OpenRouter via a generic OpenAI-compatible LLM gateway

## Context
The assistant already reaches remote LLMs through one OpenAI-compatible provider
(OpenCode Zen), but it is the only one and its wiring is hard-coded to that single
vendor. OpenRouter is a single API key that fronts many model vendors (Anthropic,
OpenAI, Google, Meta, …) under `vendor/model` names, plus a free meta-model
(`openrouter/free`) that routes each request to whatever free model can serve it.

This plumage adds OpenRouter as a selectable remote endpoint and, in doing so,
generalizes the remote LLM path so that remote gateways are *data* — a table of
name → base URL (+ optional extra headers) — rather than per-vendor code. The next
OpenAI-compatible gateway then becomes a table entry, not a new provider class.
Local Ollama remains the guaranteed offline path; remote stays an optional
accelerator behind the existing provider seam with a local fallback. The
generalization is deliberately behavior-preserving: existing `opencode-zen` configs
must keep working unchanged. The API key lives only in the environment
(`ASSISTANT_LLM__API_KEY`), never in the repo.

## User Stories
- As an operator, I want to select `openrouter` as my LLM provider (primary or
  fallback) with one API key, so that I can reach many model vendors without wiring
  each one.
- As a cost-conscious operator, I want to point at OpenRouter's free meta-model
  (`openrouter/free`), so that I can run the assistant at no cost, accepting
  variable latency and capability.
- As an existing OpenCode Zen user, I want my current `provider: opencode-zen`
  config to keep working exactly as before, so that the generalization is invisible
  to me.
- As a maintainer, I want a new OpenAI-compatible gateway to be a small data entry
  rather than a new provider class, so that future endpoints are cheap to add.
- As an offline-first operator, I want the local Ollama path unchanged and still
  the fallback, so that remote outages never break the assistant.

## Functional Criteria
Numbered, testable statements of behavior. Referenced downstream as FC-1, FC-2, …
1. FC-1: A single generic OpenAI-compatible provider implements the LLM provider
   contract (complete/chat/chat_tools/health/aclose), preserving today's wire
   behavior: bearer auth, retry/backoff with jitter on 429/5xx/transport, no retry
   on 4xx-auth, malformed-200 guards, structured logging, and OpenAI tool /
   `response_format` handling.
2. FC-2: A gateway table maps a provider name to its default base URL and an
   optional extra-headers set. It contains at least `opencode-zen` (the existing
   Zen base URL) and `openrouter` (the OpenRouter base URL). OpenRouter's entry
   carries no extra headers; the extra-headers merge seam exists but ships empty.
3. FC-3: Selecting `provider: openrouter` builds the generic provider pointed at
   OpenRouter's base URL; requests carry the configured model verbatim and, for
   tool/JSON calls, the `tools` / `response_format` fields.
4. FC-4: `provider: opencode-zen` behaves identically to today (same endpoint,
   auth, retry, and health semantics) — the generalization changes no observable
   behavior for it.
5. FC-5: The remote-vs-local branches in the composition root (endpoint logging,
   boot health warning, health path) are driven by the gateway table, not a
   hard-coded vendor string, and name whichever gateway is selected.
6. FC-6: A single shared API key serves the selected remote gateway. `base_url` is
   an optional override: blank uses the selected gateway's table default; an
   explicit value is honored, preserving existing configs.
7. FC-7: The model is always explicitly configured (no per-gateway default). Both
   `config.yaml` and `default-config.yaml` carry a commented OpenRouter example
   using `model: openrouter/free`, noting that an API key is still required and that
   free models rate-limit and rotate.
8. FC-8: `openrouter/free` works with no dedicated code path: the id is sent
   verbatim, and because tool/JSON calls declare their features, OpenRouter's free
   router filters to a capable model.

## Acceptance Criteria
Checkbox list of verifiable conditions under which this plumage is considered fledged, one `- [ ] AC-N: …` line each. Authored unchecked; checked only via `fledge criteria check` at plumage closeout.
- [ ] AC-1: With an OpenRouter key configured and `provider: openrouter`, a voice
      turn reaches OpenRouter's `/chat/completions` at the OpenRouter base URL and
      returns a spoken answer; a tool-requiring turn sends the `tools` schema and a
      returned tool call is parsed back.
- [ ] AC-2: `provider: opencode-zen` produces the same requests and behavior as
      before the change — the existing Zen wire + retry/guard tests pass unchanged
      against the generic provider.
- [ ] AC-3: The gateway table resolves `openrouter` → the OpenRouter base URL and
      `opencode-zen` → the Zen base URL; a blank `base_url` uses the table default
      while an explicit `base_url` overrides it.
- [ ] AC-4: The composition root treats `openrouter` as a remote gateway everywhere
      it treated `opencode-zen` as one (endpoint logged, boot warning names the
      gateway, health path taken), verified without a hard-coded vendor check.
- [ ] AC-5: With `model: openrouter/free`, the provider sends `openrouter/free`
      verbatim and includes `tools` / `response_format` on the calls that need them,
      with no special-casing of that id.
- [ ] AC-6: A single shared `api_key` (from `ASSISTANT_LLM__API_KEY`) is used; no
      key appears in any committed file. Both config files carry the commented
      `openrouter/free` example.
- [ ] AC-7: With `provider: openrouter` and `fallback` set to Ollama (or unset), a
      remote failure falls back to local Ollama; the full test suite passes offline
      with the remote stubbed.

## Out of Scope
- Two remote gateways at once (e.g. `openrouter` primary + `opencode-zen` fallback
  needing distinct keys/URLs) — deferred to a future plumage.
- Per-request or cost-based model routing across OpenRouter's catalog.
- Cost/usage tracking or spend caps (even though OpenRouter returns usage data).
- Streaming responses (the codebase is non-streaming throughout).
- Sending our own attribution headers (`HTTP-Referer` / `X-Title`) — the
  extra-headers seam exists but ships empty.
- A TUI control for provider/model selection (config/env only, as `opencode-zen`
  is today).

## Open Questions
- None — resolved during interrogation.
