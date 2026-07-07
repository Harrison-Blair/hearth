---
id: PLM-002
title: "AI-first web search: Tavily + Exa providers with query-type routing"
status: hatched
priority: P1
authored: 2026-07-07T07:15:24Z
agent: fledge-orchestrate/planning
fledge_version: 0.2.0
---

# PLM-002: AI-first web search: Tavily + Exa providers with query-type routing

## Context
Web search today runs on keyless scrapers (`ddgs` + Wikipedia) fanned out through
`MultiSearch`. They work offline-first but return noisy, shallow snippets that the
agentic assess loop must grade and often retry — costing rounds, latency, and answer
quality. AI-first search APIs return clean, LLM-ready content: Tavily is built for
agent retrieval and can include a synthesized answer with sourced snippets; Exa is
a neural index that matches meaning rather than keywords ("startups building AI
tools for doctors" finds health-tech companies that never use that phrasing).

This plumage adds both as `SearchProvider` implementations — the seam
`assistant/search/base.py` was explicitly designed to accept — and routes each
query by type: factual/current-events queries go to Tavily, semantic/"find me
things like" queries go to Exa. The routing decision rides the skill's existing
query-refine LLM call (one extra JSON field, no extra round-trips). The keyless
providers remain as the fallback tier, so the offline-first guarantee is
unchanged: no API key, no network, or a failed keyed call all degrade to today's
behavior — with a brief spoken notice so the user knows the good sources were
skipped.

Cloud content never gains trust: Tavily's synthesized answer and all keyed-provider
snippets flow through the same fencing, neutralization, and local-LLM assess pass
that guards the existing providers. API keys live only in the environment
(`ASSISTANT_WEB_SEARCH__*`), never in the repo.

## User Stories
- As a voice user asking about current events, I want answers drawn from an
  LLM-ready search API, so that the first round is usually sufficient and the
  answer is faster and better sourced.
- As a voice user asking exploratory questions ("find me podcasts like…"), I want
  the query answered by a semantic index, so that meaning matches even when
  keywords don't.
- As the operator of an offline-first device, I want the assistant to keep
  answering (via the keyless tier) when keys are absent or the network is down,
  and to briefly say so, so that degradation is transparent and nothing breaks.
- As a security-conscious operator, I want cloud-returned text treated as
  untrusted and my API keys kept out of the repo, so that the new providers don't
  widen the injection or secret-leak surface.

## Functional Criteria
Numbered, testable statements of behavior. Referenced downstream as FC-1, FC-2, …
1. FC-1: A `TavilySearch` provider implements the `SearchProvider` ABC, calling the
   Tavily search API with `include_answer`, and returns `SearchResult`s (plus the
   synthesized answer) from the structured response.
2. FC-2: An `ExaSearch` provider implements the `SearchProvider` ABC, calling the
   Exa search API and returning `SearchResult`s from its structured response.
3. FC-3: The skill's query-refine LLM call additionally classifies the query as
   `factual` or `semantic` in the same JSON reply; factual routes to Tavily,
   semantic to Exa. A missing/invalid classification defaults to factual.
4. FC-4: When the routed keyed provider is unconfigured (no key), unhealthy, or
   its call fails (timeout, quota, network), the skill speaks a brief in-persona
   notice and retries the same query on the keyless tier (ddgs+wikipedia) within
   the same round.
5. FC-5: Tavily's synthesized answer is passed to the assess call as one more
   fenced, neutralized, length-capped untrusted block; all keyed-provider snippets
   go through the same `_neutralize`/fencing/truncation defenses as existing
   providers. The local LLM authors everything spoken.
6. FC-6: API keys are read from config fields that default empty and are set via
   env (`ASSISTANT_WEB_SEARCH__TAVILY_API_KEY`, `ASSISTANT_WEB_SEARCH__EXA_API_KEY`);
   no key appears in `config.yaml`, `default-config.yaml`, or any committed file.
7. FC-7: With no keys configured, boot logs a clear warning and the search
   capability behaves exactly as today (keyless tier only) — providers
   health-check and degrade rather than crash, per the existing convention.
8. FC-8: All new tunables (keys, per-provider endpoints/options) are typed fields
   on `WebSearchConfig`, mirrored in `config.yaml` and `default-config.yaml`.

## Acceptance Criteria
Checkbox list of verifiable conditions under which this plumage is considered fledged, one `- [ ] AC-N: …` line each. Authored unchecked; checked only via `fledge criteria check` at plumage closeout.
- [ ] AC-1: With a Tavily key configured, a factual query ("search the web for
      <current event>") is served by Tavily: the provider returns structured
      results (and an answer block) that the assess loop consumes, and the spoken
      answer carries a source attribution.
- [ ] AC-2: With an Exa key configured, a semantic query ("find me things like…")
      routes to Exa and returns meaning-matched results.
- [ ] AC-3: The refine call's JSON carries the `query_type` field; factual →
      Tavily, semantic → Exa; an unparseable classification falls back to factual.
- [ ] AC-4: Killing the keyed provider (no key / forced failure) produces a spoken
      notice and a same-round keyless-tier answer; with no keys at all, behavior
      is identical to the current release except the one-time boot warning.
- [ ] AC-5: Injection-shaped content placed in a Tavily answer or keyed-provider
      snippet is neutralized before reaching the assess prompt (existing
      injection-defense tests extended to the new providers).
- [ ] AC-6: No API key or secret appears in any committed file; keys arrive via
      env override only.
- [ ] AC-7: The full test suite passes without the keys or network (keyed
      providers stubbed, per the repo's test convention).

## Out of Scope
- SearXNG self-hosted provider (deliberately deferred — noted for a future
  plumage).
- Brave Search API or any further keyed providers.
- Speaking Tavily's synthesized answer directly without the local assess pass.
- Content-extraction endpoints (Tavily Extract, Exa full-page contents) beyond
  the snippet/highlight fields of a search response.
- Moving routing into the orchestrator's tool schemas (a second intent).
- Changes to the agentic loop's round structure, progress speech, or persona
  beyond the new fallback notice.

## Open Questions
- Which Exa result field (highlights vs. summary vs. truncated text) best fits the
  500-char snippet cap — deferred to feather-level design.
