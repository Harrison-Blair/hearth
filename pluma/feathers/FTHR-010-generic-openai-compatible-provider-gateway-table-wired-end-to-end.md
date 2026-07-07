---
id: FTHR-010
title: "Generic OpenAI-compatible provider + gateway table, wired end-to-end"
plumage: PLM-004
status: pipping
priority: P2
depends_on: []
oversight: merge
authored: 2026-07-07T23:28:08Z
agent: fledge-orchestrate/planning
fledge_version: 0.2.0
---

# FTHR-010: Generic OpenAI-compatible provider + gateway table, wired end-to-end

## Description
The tracer slice. Extracts today's `OpenCodeZenProvider` into a single
vendor-neutral `OpenAICompatibleProvider`, introduces a gateway table (provider
name → base URL + optional extra headers) with entries for `opencode-zen` and
`openrouter`, and rewires the composition root's provider dispatch
(`_build_one_llm`) to build the generic provider for either gateway via the table,
with `base_url` as a blank-means-table-default override. The `OpenCodeZenProvider`
class is removed; the config string `opencode-zen` stays. The existing Zen wire +
retry/guard tests are repointed to the generic class so backward-compat is proven,
not assumed. After this feather, `provider: openrouter` (with a key) builds a
working provider that reaches OpenRouter's `/chat/completions`, and
`provider: opencode-zen` behaves exactly as before.

Establishes the interfaces the two follow-on feathers compose against: the
`GATEWAYS` table (FTHR-B keys diagnostics off it) and the `openrouter` entry +
verbatim-model/feature-declaration behavior (FTHR-C pins the named `openrouter/free`
contract).

Satisfies PLM-004 FC-1, FC-2, FC-3, FC-6 and the generic half of FC-8; establishes
AC-2 and AC-3.

## Affected Modules
- **`assistant/llm/` (new `openai_compatible_provider.py`; remove
  `opencode_zen_provider.py`)** — move `OpenCodeZenProvider` to
  `OpenAICompatibleProvider` (+ `LLMResponseError`, retry/guard/logging logic
  unchanged), adding an `extra_headers: dict[str, str] | None` constructor param
  merged onto the bearer auth headers. Define the `GATEWAYS` table here. See
  `.fledge/nest/architecture.md` → "The LLM path" and `data-model.md` → LLM contract.
- **`assistant/app.py`** — `_build_one_llm`: `provider in GATEWAYS` → build
  `OpenAICompatibleProvider` with `base_url = cfg.base_url or
  GATEWAYS[provider]["base_url"]` and that gateway's `extra_headers`; else Ollama.
  Update the import. (The diagnostic branches in `_run`/`main` are FTHR-B's job —
  leave them.) See `.fledge/nest/entry-points.md` → "where a new LLM provider is
  registered".
- **`assistant/core/config.py`** — `LlmConfig.base_url` default `""` (blank → table
  default). `api_key` stays shared.
- **`tests/`** — rename `test_zen_provider.py` / `test_zen_provider_guards.py` →
  `test_openai_compatible_provider*.py`, repoint imports to
  `OpenAICompatibleProvider` (they already parametrize `base_url`, so they carry
  over). Update any `base_url`-default assertion in `tests/test_config.py` /
  `test_configfile.py`.

## Approach
Test-first. Behavior-preserving move: the generic class is the current Zen provider
plus one additive `extra_headers` param (default `None` → no change). The table is
pure data:
```
GATEWAYS = {
    "opencode-zen": {"base_url": "https://opencode.ai/zen/v1", "extra_headers": {}},
    "openrouter":   {"base_url": "https://openrouter.ai/api/v1", "extra_headers": {}},
}
```
`extra_headers` merges after the auth header (`{**auth, **extra_headers}`); both
ship empty. In `_build_one_llm`, `base_url = cfg.base_url or
GATEWAYS[provider]["base_url"]` so an explicit YAML value still wins (existing
configs unaffected) and blank uses the table default. No behavior change for
`opencode-zen`; `openrouter` is a new table entry only. Never log the key.

## Tests
Repointed `tests/test_openai_compatible_provider.py` + `_guards.py`: the full
existing wire + retry/guard suite passes against `OpenAICompatibleProvider`
(backward-compat proof). Added:
- **extra_headers merge** — a provider built with `extra_headers={"X-Foo":"bar"}`
  sends that header *and* the bearer auth; empty/None leaves auth untouched.
- **gateway-table resolution** (unit on `_build_one_llm`, no network) —
  `openrouter` → OpenRouter URL, `opencode-zen` → Zen URL; blank `cfg.base_url`
  uses the table default, explicit `cfg.base_url` overrides it.
- **generic verbatim-model + feature declaration** (neutral model name) — the
  configured model id is sent unchanged; `chat_tools` includes `tools`,
  `complete(json=True)` includes `response_format`.

Implementation order fixed: (1) write tests; (2) confirm they FAIL against unchanged
code for the expected reason; (3) implement until green.

## Acceptance Criteria
- [x] AC-1: The tests listed above were observed failing before implementation and
      pass after.
- [x] AC-2: The repointed Zen wire + retry/guard suites pass unchanged against
      `OpenAICompatibleProvider`; `provider: opencode-zen` builds the same provider,
      endpoint, retry, and health behavior as before (PLM-004 AC-2, FC-4).
- [x] AC-3: The `GATEWAYS` table resolves `openrouter` → the OpenRouter base URL and
      `opencode-zen` → the Zen base URL; `_build_one_llm` treats a blank `base_url`
      as the table default and an explicit `base_url` as an override
      (PLM-004 AC-3, FC-6).
- [x] AC-4: `provider: openrouter` with a key builds an `OpenAICompatibleProvider`
      targeting OpenRouter; the generic provider sends any configured model verbatim,
      includes `tools`/`response_format` on the calls that need them, and merges
      `extra_headers` onto auth (PLM-004 FC-1, FC-2, FC-3, generic FC-8).
- [x] AC-5: `ruff check assistant tests` and the full suite pass with no network
      (remote stubbed via httpx MockTransport).
