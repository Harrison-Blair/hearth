---
id: FTHR-003
title: "Tracer: routed web-search seam + Tavily provider end-to-end"
plumage: PLM-002
status: hatching
priority: P1
depends_on: []
oversight: merge
authored: 2026-07-07T07:21:06Z
agent: fledge-orchestrate/planning
fledge_version: 0.2.0
---

# FTHR-003: Tracer: routed web-search seam + Tavily provider end-to-end

## Description
The tracer-bullet slice for PLM-002: a complete, working AI-first search path for
factual queries, plus the routing/fallback seam that FTHR-004 later plugs Exa into.
Delivers four things that compose into one vertical slice — spoken query → refine
(+type) → Tavily → fenced results+answer → assess → spoken sourced answer, degrading
to the keyless tier with a spoken notice:

1. **Config surface**: `WebSearchConfig` gains `tavily_api_key: str = ""`,
   `exa_api_key: str = ""` (reserved for FTHR-004), and any per-provider tunables
   needed (e.g. `tavily_endpoint`). Mirrored in `config.yaml` and
   `default-config.yaml` with empty key values; real keys arrive only via
   `ASSISTANT_WEB_SEARCH__TAVILY_API_KEY` / `__EXA_API_KEY` env overrides.
2. **`TavilySearch` provider** (`assistant/search/tavily.py`): implements the
   `SearchProvider` ABC over `httpx` (POST /search, `include_answer=True`).
   Parses the structured response into `SearchResult`s; the synthesized answer is
   carried as an additional `SearchResult` with a distinguishable source (e.g.
   `source="tavily"`, title "answer") so it flows through the existing merge,
   fencing, and neutralization unchanged. `health()` = cheap authenticated probe;
   constructible from primitive config values only.
3. **Routed dispatch in `WebSearchSkill`**: `_refine`'s single LLM JSON call now
   returns `{"query": …, "query_type": "factual"|"semantic"}` (missing/invalid →
   factual). The skill takes a mapping of route → provider plus the keyless-tier
   provider; each round it searches the routed keyed provider first and, on
   empty-due-to-failure/missing key, speaks a brief in-persona notice (existing
   `_say_soon` seam) and retries the same query on the keyless tier within the
   round. The `semantic` route falls back to the factual route until FTHR-004
   registers Exa.
4. **Wiring** (`assistant/app.py:_build_search`): constructs `TavilySearch` only
   when its key is set, keeps the existing `MultiSearch(ddgs+wikipedia)` as the
   keyless tier, injects the route mapping into `WebSearchSkill`, and logs a clear
   boot warning when no keys are configured (keyless-only behavior — identical to
   today).

Satisfies PLM-002 FC-1, FC-3 (factual half), FC-4..FC-8. FC-2 and the semantic
half of FC-3 land in FTHR-004.

## Affected Modules
- **`assistant/search/` (new `tavily.py`)** — model on `wikipedia.py` (httpx
  provider with owned client, `aclose()`); see `.fledge/nest/architecture.md`
  → "Web-search capability" and `data-model.md` → SearchResult/SearchProvider seam.
- **`assistant/skills/web_search.py`** — `_refine` JSON shape, routed dispatch +
  fallback notice; keep the injection defenses (`_neutralize`, fencing, caps)
  untouched and apply them to all new content.
- **`assistant/core/config.py`** + **`config.yaml`** + **`default-config.yaml`** —
  new `WebSearchConfig` fields (see `data-model.md`, which flags the missing
  API-key field; secrets-in-env precedent: `LlmConfig`).
- **`assistant/app.py`** — `_build_search` registry + boot warning (see
  `entry-points.md` → "the function a new provider must be added to").

## Approach
Test-first. Introduce the route mapping as a constructor argument on
`WebSearchSkill` (e.g. `routes: dict[str, SearchProvider]` + existing default
provider as the keyless tier) so unit tests inject stubs without config.
`TavilySearch` owns its `httpx.AsyncClient`; timeouts come from
`WebSearchConfig.timeout`. Never log the API key. The Tavily answer block rides the
existing `SearchResult` path (one more fenced block) rather than a new prompt
channel, so FC-5's defenses need no new mechanism — only tests proving they cover
it. The fallback notice reuses the retry-remark speech path with a fixed
in-persona line; no new persona machinery.

## Tests
New `tests/test_tavily_provider.py` (stubbed httpx transport, per repo convention —
suite must pass with no network/keys):
- parses a canned Tavily response into `SearchResult`s (titles, snippets, source
  domains, URLs) and surfaces the synthesized answer block
- `health()` False / `search()` raising on HTTP error, timeout honored
- injection-shaped content in the response arrives as data (str), untouched here

Extended `tests/test_web_search_skill.py`:
- refine JSON with `query_type: factual` routes to the factual provider;
  missing/garbage type defaults to factual
- routed-provider failure (raises/empty-key) → spoken notice + same-round keyless
  answer; no keyed provider configured → keyless-only, no notice spam
- a Tavily answer block containing injection text is neutralized/fenced in the
  assess prompt (extend the existing injection-defense assertions)

Config: a case asserting env override `ASSISTANT_WEB_SEARCH__TAVILY_API_KEY`
populates the field and the default is empty.

Implementation order is fixed: (1) write the tests; (2) run them against the
unchanged code and confirm they FAIL for the expected reason; (3) implement until
they pass.

## Acceptance Criteria
- [x] AC-1: The tests listed above were observed failing before implementation and
      pass after.
- [x] AC-2: With a stubbed Tavily response, a factual query end-to-end through
      `WebSearchSkill` produces a spoken answer with source attribution, consuming
      the Tavily results + fenced answer block (PLM-002 AC-1 path).
- [x] AC-3: Routed-provider failure yields the spoken notice and a same-round
      keyless-tier answer; with no keys configured behavior matches today's plus
      the one-time boot warning (PLM-002 AC-4).
- [x] AC-4: Injection content in Tavily answer/snippets is neutralized before the
      assess prompt (PLM-002 AC-5).
- [x] AC-5: No key appears in any committed file; keys land via env only
      (PLM-002 AC-6); `ruff check assistant tests` and the full suite pass with no
      network (PLM-002 AC-7).
