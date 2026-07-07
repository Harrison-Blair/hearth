---
id: FTHR-004
title: "Exa provider + semantic query route"
plumage: PLM-002
status: hatching
priority: P1
depends_on: [FTHR-003]
oversight: merge
authored: 2026-07-07T07:22:44Z
agent: fledge-orchestrate/planning
fledge_version: 0.2.0
---

# FTHR-004: Exa provider + semantic query route

## Description
Widens FTHR-003's tracer slice with the second keyed provider: an `ExaSearch`
implementation of the `SearchProvider` ABC and activation of the `semantic` route
that FTHR-003 left falling back to factual. After this feather, a "find me things
like…" query classified `semantic` by the refine call is served by Exa's neural
index, with the same keyless-tier fallback + spoken notice behavior FTHR-003
established (that machinery is route-agnostic and needs no changes — only a
registry entry).

Resolves PLM-002's open question: which Exa response field to map into
`SearchResult.snippet` given the 500-char `max_snippet_chars` cap. Direction:
request Exa **highlights** (short, relevance-ranked excerpts) rather than full
`text` — they fit the cap without wasting tokens on truncated page dumps; fall
back to a truncated `text`/`summary` field when highlights are absent.

Satisfies PLM-002 FC-2 and the semantic half of FC-3.

## Affected Modules
- **`assistant/search/` (new `exa.py`)** — model on `tavily.py` from FTHR-003
  (httpx provider, owned client, `aclose()`, key via config); see
  `.fledge/nest/architecture.md` → "Web-search capability".
- **`assistant/app.py`** — one `_build_search` registry entry: construct
  `ExaSearch` when `exa_api_key` is set and map it to the `semantic` route.
- **`config.yaml` / `default-config.yaml`** — only if Exa needs tunables beyond
  the `exa_api_key` field FTHR-003 already added (e.g. `exa_endpoint`).

## Approach
Test-first. `ExaSearch` POSTs to Exa's `/search` with
`contents: {highlights: …}`, auth via `x-api-key` header, `num_results` from
`count`. Map each result to `SearchResult(title, snippet=joined highlights,
source=domain(url), url)`. Reuse `search.base.domain()` for attribution. No skill
changes: FTHR-003's route mapping means registering the provider under
`"semantic"` is the entire integration. Never log the key.

## Tests
New `tests/test_exa_provider.py` (stubbed httpx transport; no network/keys):
- parses a canned Exa response (highlights present) into `SearchResult`s with
  domain attribution
- falls back to truncated text/summary when highlights are absent; snippet
  respects `max_snippet_chars`
- `health()` False / `search()` raising on HTTP error

Extended `tests/test_web_search_skill.py`:
- refine JSON `query_type: semantic` routes to the semantic provider when
  registered, and to the factual/keyless path when not

Implementation order is fixed: (1) write the tests; (2) confirm they FAIL against
unchanged code for the expected reason; (3) implement until they pass.

## Acceptance Criteria
- [ ] AC-1: The tests listed above were observed failing before implementation and
      pass after.
- [ ] AC-2: A semantic query end-to-end through `WebSearchSkill` (stubbed Exa) is
      served by `ExaSearch` and produces a spoken, attributed answer
      (PLM-002 AC-2).
- [ ] AC-3: Exa failure/missing key degrades exactly as FTHR-003's fallback
      contract (spoken notice + keyless tier) with no code changes to the skill.
- [ ] AC-4: No key in committed files; `ruff check assistant tests` and the full
      suite pass with no network (PLM-002 AC-6/AC-7).
