---
id: FTHR-015
title: "Secrets/config surface — strip secrets from YAML, secrets-only .env.example"
plumage: PLM-005
status: egg
priority: P2
depends_on: [FTHR-013]
authored: 2026-07-08T01:04:05Z
agent: fledge-orchestrate/planning
fledge_version: 0.2.0
---

# FTHR-015: Secrets/config surface — strip secrets from YAML, secrets-only .env.example

## Description
Completes the separation of concern on the operator-facing surface: removes every
secret-bearing field from `config.yaml` and `default-config.yaml` (so a committed
YAML file cannot leak a key), rewrites `.env.example` to document only credentials,
and updates the config files' provider comments/examples to `opencode_zen` (the
daemon rename shipped in FTHR-013). Secrets are sourced exclusively from `.env`/env
after this. Satisfies PLM-005 FC-6, FC-7; establishes PLM-005 AC-5, AC-6.

## Affected Modules
- **`config.yaml`** — remove `llm.api_key`, `web_search.tavily_api_key`,
  `web_search.exa_api_key`; leave a one-line pointer comment where they were
  (`# api keys → .env; see .env.example`). Update the commented provider example and
  any `opencode-zen` enumeration to `opencode_zen`. `base_url` and
  `calendar.credentials_path` stay (config, not secrets). See
  `.fledge/nest/data-model.md` → config surface.
- **`default-config.yaml`** — same field removals + pointer comments; update the
  `# ollama | opencode-zen | openrouter` enumeration and commented blocks to
  `opencode_zen`.
- **`.env.example`** — rewrite **secrets-only**:
  `ASSISTANT_LLM__OPENROUTER_API_KEY`, `ASSISTANT_LLM__OPENCODE_ZEN_API_KEY`,
  `ASSISTANT_WEB_SEARCH__TAVILY_API_KEY`, `ASSISTANT_WEB_SEARCH__EXA_API_KEY`, each
  with a brief comment. Drop the non-secret override examples
  (model/host/wake/stt/audio/verify/logging).
- **`tests/`** — new `tests/test_no_secrets_in_config.py` (loads both shipped YAMLs;
  asserts no secret-named field; asserts `.env.example` lists the credential vars and
  no non-secret `ASSISTANT_*` override). No overlap with FTHR-013/014 test files.

## Approach
Test-first. YAML edits are field removals + comments; the behavioral guarantee —
"no secret ever sits in committed YAML" — is pinned by a test that loads the shipped
files and asserts it, so the separation can't silently regress. Provider-string
updates here are comment/example-only (the daemon-side rename was FTHR-013).
`.env.example` becomes the single discoverable list of required secrets.

## Tests
New `tests/test_no_secrets_in_config.py` (offline; reads the repo files):
- **no secrets in YAML** — parse `config.yaml` and `default-config.yaml`; assert no
  field name is `api_key` or ends in `_api_key`/`token`/`secret`/`password` at any
  nesting (fails today: `api_key`/`tavily_api_key`/`exa_api_key` present).
- **`.env.example` is secrets-only** — contains the four credential vars; contains no
  non-secret `ASSISTANT_*` override (e.g. no `ASSISTANT_LLM__MODEL`).

Fixed order: (1) write the tests; (2) confirm they FAIL against the current files;
(3) edit the files until they pass.

## Acceptance Criteria
- [x] AC-1: The tests listed above were observed failing before implementation and
      pass after.
- [x] AC-2: `config.yaml` and `default-config.yaml` contain no secret-bearing fields;
      secrets come only from `.env`/env (PLM-005 FC-6, AC-5).
- [x] AC-3: `.env.example` documents only the credential vars and no non-secret
      overrides (PLM-005 FC-7, AC-6).
- [x] AC-4: `ruff check assistant tests` and the full suite pass offline.
