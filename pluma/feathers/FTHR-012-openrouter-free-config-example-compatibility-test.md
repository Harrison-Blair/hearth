---
id: FTHR-012
title: "openrouter/free config example + compatibility test"
plumage: PLM-004
status: fledged
priority: P2
depends_on: [FTHR-010]
authored: 2026-07-07T23:33:04Z
agent: fledge-orchestrate/planning
fledge_version: 0.2.0
---

# FTHR-012: openrouter/free config example + compatibility test

## Description
Completes the plumage's user-facing surface. Documents how to turn OpenRouter on —
a copy-pasteable commented `openrouter/free` example in both `config.yaml` and
`default-config.yaml` — and pins the named `openrouter/free` compatibility contract
with a focused test: the id reaches the wire verbatim and tool/JSON calls declare
their features, so OpenRouter's free router filters to a capable model (no special
code path). Blanks `default-config.yaml`'s `base_url` so switching `provider` is a
one-line change (the table supplies the gateway default), matching FTHR-010's
blank→table-default resolution. No secret is committed; the key stays in
`ASSISTANT_LLM__API_KEY`.

Satisfies PLM-004 FC-7, FC-8; establishes AC-5, AC-6.

## Affected Modules
- **`default-config.yaml`** — set `base_url: ""` with a comment that blank = the
  selected gateway's default from the table; extend the provider comment to
  `# ollama | opencode-zen | openrouter`; add a commented OpenRouter block
  (`provider: openrouter`, `model: openrouter/free`, `api_key` via env,
  `fallback: ollama`) with the caveats (key still required; free models
  rate-limit/rotate).
- **`config.yaml`** — add the same commented OpenRouter example beside the active
  `llm` block (active values unchanged — it stays on `opencode-zen`).
- **`tests/` (new `tests/test_openrouter_compat.py`)** — the named `openrouter/free`
  contract against `OpenAICompatibleProvider` (stubbed httpx; no network). Update
  any test asserting `default-config.yaml`'s `base_url` value, if present.

## Approach
Test-first. The compat test builds
`OpenAICompatibleProvider(model="openrouter/free",
base_url=GATEWAYS["openrouter"]["base_url"], api_key="k")` over a MockTransport and
asserts: `complete`/`chat` send `"model": "openrouter/free"` verbatim;
`chat_tools(tools=…)` includes `tools`; `complete(json=True)` includes
`response_format`. This documents that `openrouter/free` needs no special-casing —
the same feature-declaring calls let the free router pick a capable model. The YAML
edits are comment/example only except the one `base_url: ""` default in
`default-config.yaml`. Never commit a key.

## Tests
New `tests/test_openrouter_compat.py` (stubbed httpx transport; no network/keys):
- `model: openrouter/free` is sent verbatim in `complete` / `chat` / `chat_tools`
  payloads.
- `chat_tools(tools=…)` includes the `tools` array; `complete(json=True)` includes
  `response_format: {"type": "json_object"}` — the feature declarations the free
  router filters on.
Implementation order fixed: (1) tests; (2) confirm FAIL against unchanged code (test
file absent); (3) implement until green.

## Acceptance Criteria
- [x] AC-1: The tests listed above were observed failing before implementation and
      pass after.
- [x] AC-2: `model: openrouter/free` reaches the wire verbatim and
      `tools`/`response_format` are present on the calls that need them, with no
      branch special-casing that id (PLM-004 AC-5, FC-8).
- [x] AC-3: Both `config.yaml` and `default-config.yaml` carry a commented,
      copy-pasteable `openrouter/free` example (provider / model / api_key-via-env /
      fallback + caveats); `default-config.yaml`'s `base_url` is blank so a provider
      switch needs no base_url edit; no API key appears in any committed file
      (PLM-004 AC-6, FC-7).
- [x] AC-4: `ruff check assistant tests` and the full suite pass with no network.
