---
id: FTHR-013
title: "Config core — daemon .env loading + per-provider LLM keys"
plumage: PLM-005
status: pipping
priority: P2
depends_on: []
oversight: merge
authored: 2026-07-08T01:01:08Z
agent: fledge-orchestrate/planning
fledge_version: 0.2.0
---

# FTHR-013: Config core — daemon .env loading + per-provider LLM keys

## Description
The tracer slice. Makes the daemon load `.env` directly and replaces the single
shared LLM key with per-provider keys, proving the end-to-end path: a key in
`.env` → daemon loads it → `_build_one_llm` selects the selected provider's key →
provider built. Renames the `opencode-zen` gateway to `opencode_zen` on the
**daemon side** (gateway table, config, boot diagnostics). Drops `llm.api_key`.
Satisfies PLM-005 FC-1, FC-2, FC-3, FC-4 and the daemon half of FC-5; establishes
the `*_api_key` field contract FTHR-014/015 compose against.

## Affected Modules
- **`assistant/core/config.py`** — add `env_file=".env"` to `SettingsConfigDict`;
  insert `dotenv_settings` into `settings_customise_sources` as `(init_settings,
  env_settings, dotenv_settings, YamlConfigSettingsSource(...))` (precedence
  init > env > .env > yaml). `LlmConfig`: remove `api_key`; add
  `openrouter_api_key: str = ""` and `opencode_zen_api_key: str = ""`. See
  `.fledge/nest/data-model.md` → config models, `entry-points.md` → settings sources.
- **`assistant/llm/openai_compatible_provider.py`** — rename the `GATEWAYS` key
  `"opencode-zen"` → `"opencode_zen"`. See `.fledge/nest/architecture.md` → the LLM path.
- **`assistant/app.py`** — `_build_one_llm`: resolve
  `key = getattr(cfg, f"{provider}_api_key", "")` (provider strings are now valid
  identifiers: `openrouter`, `opencode_zen`, `ollama`); pass it as `api_key=`; the
  empty-key warning fires on the resolved key. Update the config-dump masking
  (currently masks `llm.api_key`) to mask the per-provider key fields. Diagnostics
  already key off `GATEWAYS`, so `opencode_zen` flows through. See
  `.fledge/nest/entry-points.md` → where the LLM provider is registered.
- **`tests/`** — `test_config.py` (drop `api_key`; add per-provider fields +
  `.env`-loading + precedence tests), `test_llm_dispatch.py` (`opencode_zen`
  resolution + per-provider key selection), `test_app_llm_diagnostics.py` (repoint
  to `opencode_zen`). **TUI files/tests are untouched — that is FTHR-014.**

## Approach
Test-first. `.env` loading: `env_file=".env"` + `dotenv_settings` in the source
tuple; tests use pydantic's `Config(_env_file=<tmp>)` init override to point at a
temp `.env` without depending on CWD. Per-provider selection: since provider
strings are now identifiers, `getattr(cfg, f"{provider}_api_key", "")` picks the
right key for both the primary and the fallback provider (Ollama needs none). No
shared `api_key` remains. Keep `_gateway_base_url`/base_url-override logic as-is.
Never log a key.

## Tests
New/updated (all offline; httpx stubbed where a provider is built):
- **`.env` loaded by daemon** — a temp `.env` with
  `ASSISTANT_LLM__OPENROUTER_API_KEY=k1` → `cfg.llm.openrouter_api_key == "k1"`
  (fails today: dotenv is dropped from the sources).
- **precedence** — an exported `ASSISTANT_LLM__OPENROUTER_API_KEY` beats the `.env`
  value; the `.env` value beats `config.yaml`.
- **per-provider selection** — `_build_one_llm(cfg, "openrouter", …)` uses
  `openrouter_api_key`; `"opencode_zen"` uses `opencode_zen_api_key`; the other
  provider's key is not used.
- **rename** — `GATEWAYS["opencode_zen"]` resolves the Zen base URL; `"opencode-zen"`
  is absent (no longer a gateway).
- **no shared key** — `LlmConfig` has no `api_key` attribute.

Fixed order: (1) write the tests; (2) confirm they FAIL against unchanged code for
the expected reason; (3) implement until they pass.

## Acceptance Criteria
- [x] AC-1: The tests listed above were observed failing before implementation and
      pass after.
- [x] AC-2: The daemon loads `.env` directly with precedence
      init > env > `.env` > `config.yaml` (PLM-005 FC-1, FC-2).
- [x] AC-3: Each gateway uses its own per-provider key selected automatically; no
      shared `llm.api_key` exists (PLM-005 FC-3, FC-4).
- [x] AC-4: `opencode_zen` resolves as the gateway in the table and daemon
      diagnostics; `opencode-zen` no longer resolves (daemon half of PLM-005 FC-5).
- [x] AC-5: `ruff check assistant tests` and the full suite pass offline.
