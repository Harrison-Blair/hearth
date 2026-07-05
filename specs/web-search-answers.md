# Spec: Web search rework — answer the question, not "summarize results"

Status: ready for implementation
Author: Harrison (via spec session, 2026-07-03)

## Context

The current web_search skill produces answers that are hard to understand and
frequently don't address the question. Root causes, in order of impact:

1. **The user's question never reaches the summarizer.** The summary prompt is
   literally "Summarize these search results:" (`WebSearchSkill._summary_prompt`,
   `assistant/skills/web_search.py`) — the LLM is never told what was asked, so
   it produces a generic digest of three snippets.
2. **Wikipedia is the only provider.** Encyclopedia lead paragraphs cannot
   answer news, "latest on X", weather, prices, or how-to questions — exactly
   the queries the trigger phrases ("what's the latest on…") invite.
3. **Only intro extracts, truncated to 500 chars**, are ever seen by the LLM;
   answers deeper in a page are lost before summarization.
4. **No non-answer handling** — irrelevant results are summarized as
   confidently as relevant ones.

## Decisions (confirmed with the author)

- **Provider strategy**: re-add the keyless general-web DDGS provider (the
  deleted `ddgs_provider.py` is recoverable via
  `git show a39e0f2:assistant/search/ddgs_provider.py`) as the primary, with
  Wikipedia as the fallback.
- **Deep fetch**: yes, but **not blindly on result #1**. Observed problem: the
  top results are often promoted or unrelated to the question. An LLM
  relevance-selection step over the snippets picks which result (if any) is
  actually answering the question before anything is fetched.
- **No-answer behavior**: admit it, then give the closest material, hedged.

## Behavior

- "Search the web for the tallest building in the world" → a one-to-two
  sentence spoken **answer to that question** ("The tallest building is the
  Burj Khalifa at 828 meters, according to wikipedia.org."), not a topic
  digest.
- Questions the results genuinely don't answer → "I couldn't find a direct
  answer, but here's what I found: <one hedged sentence>."
- Provider failure (network down, provider blocked) → automatic fallback to
  the next provider; all providers failing → existing apology, `success=False`.
- Existing security posture is preserved and extended: fetched page text is
  untrusted, fenced, truncated, and the prompt forbids following instructions
  in it (same rules as today's `_SUMMARY_SYSTEM`).

## Design

### 1. Pass the question through to the summarizer (highest value, smallest change)

In `assistant/skills/web_search.py`:

- `_summary_prompt(results)` becomes `_answer_prompt(question, results)` and
  includes the original transcript (and the refined query), e.g.:
  `User's question: "<transcript>"\nSearch results:\n<fenced blocks>`.
- `_SUMMARY_SYSTEM` is rewritten from "summarize" to "answer": answer the
  user's question in one or two short plain spoken sentences using ONLY the
  results; end with "according to <source>"; if the results do not contain
  the answer, start the reply with "I couldn't find a direct answer, but" and
  give the closest relevant fact in one hedged sentence. Keep the SECURITY
  paragraph verbatim.

### 2. Fallback provider chain

- New `FallbackSearch(SearchProvider)` in `assistant/search/fallback.py`:
  constructed with an ordered list of providers; `search()` tries each in
  order, moving on when one raises or returns `[]`; `health()` is true if any
  provider is healthy; `aclose()` closes all. The skill stays completely
  unaware — it still holds one `SearchProvider`.
- Resurrect `DdgsSearch` from git history (`assistant/search/ddgs_provider.py`
  at commit `a39e0f2`) and its tests; re-add its dependency to `pyproject.toml`
  if it had one (check the deleted file — it may be pure httpx).
- Wiring in `app.py` only:
  `search = FallbackSearch([DdgsSearch(...), WikipediaSearch(...)])`, driven by
  a new config field (see 4).

### 3. Relevance selection, then deep fetch

The skill's flow becomes: refine → search → **select** → fetch → answer.

- **Select**: one LLM call over the result snippets, asked which single result
  actually addresses the user's question. Prompt returns strict JSON,
  mirroring the existing `_REFINE_PROMPT` pattern:
  `{"index": <1-based index or 0 if none are relevant>}`. The prompt must tell
  the model to treat promoted/advertorial and off-topic results as
  irrelevant, and it sees the fenced, untrusted snippets under the same
  SECURITY rules as the answer prompt.
  - `index >= 1` → that result is deep-fetched and the **selected results
    only** (the chosen one plus any others the model wasn't asked to exclude —
    keep it simple: pass all snippets to the answer step, but the fetched text
    only for the selected one) go to the answer step.
  - `index == 0` → skip the fetch and go straight to the no-answer reply:
    "I couldn't find a direct answer, but here's what I found: <one hedged
    sentence from the closest snippet>" (that sentence comes from the answer
    prompt, which is told no result was judged relevant).
  - Selection-call failure (bad JSON, LLM error) → degrade to fetching
    result 1, today's implicit behavior; selection is best-effort like refine.

- `SearchProvider` (`assistant/search/base.py`) gains an optional method
  `async def fetch(self, result: SearchResult) -> str` returning fuller plain
  text for one result; the base implementation returns `""` (snippets-only
  providers need no change).
  - `WikipediaSearch.fetch`: re-query the Action API for that page **without**
    `exintro`, plain text, truncated to the configured `page_chars`.
  - `DdgsSearch.fetch`: HTTP GET the result URL and reduce HTML to text.
    Prefer no new dependency (strip `<script>/<style>` then tags via regex is
    acceptable for spoken summaries); if that proves too dirty in practice,
    `beautifulsoup4` is the approved fallback dependency.
  - `FallbackSearch.fetch`: delegate to the provider that produced the result
    (track provenance, e.g. tag the provider on the `SearchResult` or keep an
    internal map).
- The skill calls `fetch()` on the **selected** result; a non-empty return is
  added to the answer prompt as an extra fenced block labelled
  `[full text of result N]`, truncated to `page_chars`. A fetch failure is
  logged and ignored — snippets alone must still produce an answer
  (offline-first degradation).

### 4. Config (`assistant/core/config.py` `WebSearchConfig` + both YAML files)

- `providers: list[str] = ["ddgs", "wikipedia"]` — order defines the fallback
  chain; names map to concrete classes in `app.py` (the composition root; the
  skill and providers never read this).
- `page_chars: int = 4000` — cap on deep-fetched text fed to the LLM.
- Existing fields (`language`, `result_count`, `timeout`,
  `max_snippet_chars`) unchanged.

### Out of scope

- Keyed APIs (Tavily/Brave) — the `SearchProvider` ABC already reserves that
  seam; nothing here should preclude a later keyed provider.
- Query classification / routing different question types to different
  providers (the fallback chain makes this unnecessary for now).
- Caching results, multi-result deep fetch, or follow-up questions
  ("tell me more") — the reply seam from `specs/mute-for-duration.md` could
  host that later.

## Files to change

- `assistant/skills/web_search.py` — answer-style prompt with question passed
  through; deep-fetch call
- `assistant/search/base.py` — `fetch()` default method
- `assistant/search/wikipedia.py` — `fetch()` implementation
- `assistant/search/ddgs_provider.py` — resurrected from `a39e0f2`, plus `fetch()`
- `assistant/search/fallback.py` — new `FallbackSearch`
- `assistant/search/__init__.py`, `assistant/app.py`, `assistant/core/config.py`,
  `config.yaml`, `default-config.yaml` — exports, wiring, config
- Tests: `tests/test_web_search_skill.py` (extend), `tests/test_wikipedia_provider.py`
  (extend for fetch), `tests/test_ddgs_provider.py` (resurrect + fetch),
  `tests/test_fallback_search.py` (new), `tests/test_config.py` (new fields)

## Acceptance criteria

All as pytest tests with stub providers/LLM (no network, matching suite style):

1. The prompt sent to the LLM for the answer contains the user's original
   transcript verbatim (assert on the stub LLM's captured prompt).
2. The system prompt instructs answering the question and the no-answer
   hedge; the SECURITY paragraph is still present.
3. `FallbackSearch`: provider 1 raises → provider 2's results are returned;
   provider 1 returns `[]` → provider 2 is tried; both fail → skill replies
   with the apology, `success=False`.
4. Relevance selection: with a stub LLM returning `{"index": 2}`, `fetch()` is
   called on result 2 (not result 1); returning `{"index": 0}` skips `fetch()`
   entirely and the answer prompt tells the model no result was relevant;
   selection returning malformed JSON degrades to fetching result 1.
5. Deep fetch: a provider returning text from `fetch()` results in an extra
   fenced block in the LLM prompt, truncated to `page_chars`; `fetch()`
   raising does not fail the turn (answer still produced from snippets).
6. `WikipediaSearch.fetch` requests the full extract (no `exintro`) for the
   right page and truncates to `page_chars` (mock the HTTP layer, matching
   `tests/test_wikipedia_provider.py`'s existing approach).
7. Config: `providers` and `page_chars` parse from YAML and are overridable
   via `ASSISTANT_WEB_SEARCH__*` env vars.
8. Wiring: `app.py` builds the chain in configured order; an unknown provider
   name fails at boot with a clear error.

## Verification

- `pytest` green, `ruff check assistant tests` clean.
- Manual, online: `python -m tui`, type "search the web for <a current-events
  question>" and "<an encyclopedic question>" — both should get direct spoken
  answers with attribution; ask something obscure and confirm the hedged
  no-answer phrasing.
- Manual, degraded: set `providers: ["wikipedia"]` (or disconnect) and confirm
  fallback/apology paths instead of a crash.
