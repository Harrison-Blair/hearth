---
id: PLM-005
title: "Secrets in .env, configuration in config.yaml — per-provider LLM credentials"
status: fledged
priority: P2
authored: 2026-07-08T00:59:24Z
agent: fledge-orchestrate/planning
fledge_version: 0.2.0
---

# PLM-005: Secrets in .env, configuration in config.yaml — per-provider LLM credentials

## Context
The assistant's credentials (the LLM API key, web-search keys) and its ordinary
configuration currently share `config.yaml` as empty placeholder slots, and a
single shared LLM key must be edited every time the operator switches providers.
Separately, the daemon does not read `.env` on its own — `.env` reaches it only
when launched through the monitor TUI (the supervisor merges it into the child
environment), so a directly-launched daemon silently ignores secrets placed in
`.env`. This plumage separates the two concerns: secrets (API keys, credentials)
live only in `.env`; `config.yaml` holds only non-secret configuration. It makes
the daemon load `.env` directly so secrets apply regardless of launch path, and
replaces the single shared LLM key with one key per provider, so switching
providers is a one-line `provider` change with no credential edit. The
`opencode-zen` provider is renamed `opencode_zen` for a clean 1:1
provider-to-env-var mapping. Plaintext, gitignored `.env` remains the storage; no
secrets manager is introduced.

## User Stories
- As an operator, I want each LLM provider's API key set independently in `.env`,
  so I can switch providers by changing only `provider` — never re-pasting a key.
- As an operator, I want the daemon to read `.env` whether I launch it via the TUI
  or directly, so my secrets load consistently.
- As a security-conscious operator, I want `config.yaml` to contain no secret
  fields, so I can commit it with zero risk of leaking a key.
- As an operator, I want a secrets-focused `.env.example`, so it's obvious exactly
  which credentials I must provide.

## Functional Criteria
Numbered, testable statements of behavior. Referenced downstream as FC-1, FC-2, …
1. FC-1: The daemon loads `.env` directly (not only via the TUI), so `ASSISTANT_*`
   values in `.env` apply on any launch path.
2. FC-2: Source precedence is explicit init args > exported env vars > `.env` >
   `config.yaml`.
3. FC-3: Each keyed LLM gateway has its own API-key setting from its own env var
   (`openrouter` → `ASSISTANT_LLM__OPENROUTER_API_KEY`, `opencode_zen` →
   `ASSISTANT_LLM__OPENCODE_ZEN_API_KEY`); the selected provider automatically uses
   its own key. Switching provider requires no key edit.
4. FC-4: There is no single shared LLM `api_key` — it is removed.
5. FC-5: The `opencode-zen` provider is renamed `opencode_zen` everywhere (config
   values, gateway table, TUI display and selection, diagnostics). The old
   hyphenated string is no longer accepted as that gateway.
6. FC-6: `config.yaml` and `default-config.yaml` contain no secret-bearing fields;
   secrets come only from `.env`/env. `calendar.credentials_path` (a filesystem
   path, not a secret) remains configuration.
7. FC-7: `.env.example` documents only secrets (per-provider LLM keys + web-search
   keys), not non-secret overrides.

## Acceptance Criteria
Checkbox list of verifiable conditions under which this plumage is considered fledged, one `- [ ] AC-N: …` line each. Authored unchecked; checked only via `fledge criteria check` at plumage closeout.
- [x] AC-1: With a directly-launched daemon and `ASSISTANT_LLM__OPENROUTER_API_KEY`
      in `.env`, an `openrouter` turn uses that key; switching to
      `provider: opencode_zen` with `ASSISTANT_LLM__OPENCODE_ZEN_API_KEY` set uses
      the zen key — with no other edit.
- [x] AC-2: An exported `ASSISTANT_*` var overrides the same key from `.env`, which
      overrides `config.yaml`.
- [x] AC-3: No shared `llm.api_key` exists; per-provider keys are the sole LLM
      credential source and the selected provider's key is chosen automatically.
- [x] AC-4: `opencode_zen` works end-to-end (daemon build, TUI picker/label,
      diagnostics); `opencode-zen` no longer resolves as that gateway.
- [x] AC-5: `config.yaml` and `default-config.yaml` contain no api-key fields
      (committing them cannot leak a secret); the full suite passes offline.
- [x] AC-6: `.env.example` lists only the credential vars and no non-secret
      overrides.

## Out of Scope
- Encrypting `.env` or integrating a secrets manager/keyring — `.env` stays
  plaintext and gitignored.
- Moving the Google service-account JSON into `.env` (it stays a file referenced by
  `credentials_path`).
- Per-provider `base_url` overrides beyond today's single `base_url` field.
- A back-compat alias for the old `opencode-zen` string.
- Disabling `.env` for non-secret overrides — the mechanism still accepts any
  `ASSISTANT_*` var; only `.env.example` stops advertising non-secrets.

## Open Questions
None — resolved during interrogation.
