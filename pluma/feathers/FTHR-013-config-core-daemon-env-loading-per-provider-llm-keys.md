---
id: FTHR-013
title: "Config core + provider rename — .env loading, per-provider LLM keys, opencode_zen (daemon + TUI)"
plumage: PLM-005
status: hatching
priority: P2
depends_on: []
oversight: merge
authored: 2026-07-08T01:01:08Z
agent: fledge-orchestrate/planning
fledge_version: 0.2.0
---

# FTHR-013: Config core + provider rename — .env loading, per-provider LLM keys, opencode_zen (daemon + TUI)

## Description
The tracer slice. Makes the daemon load `.env` directly and replaces the single
shared LLM key with per-provider keys, proving the end-to-end path: a key in
`.env` → daemon loads it → `_build_one_llm` selects the selected provider's key →
provider built. Renames the `opencode-zen` provider to `opencode_zen` across **both the daemon and
the TUI** (gateway table, config, boot diagnostics, TUI pickers/label/health probe),
and drops `llm.api_key` everywhere it is read — including the TUI, which consumes it
in `_probe_provider` and `_select_options`. The rename and the `api_key` removal are
one atomic cross-cutting change (this feather absorbs the former FTHR-014, since the
TUI reads `llm.api_key` and the two edits are entangled in the same functions).
Satisfies PLM-005 FC-1, FC-2, FC-3, FC-4, FC-5; establishes the `*_api_key` field
contract FTHR-015 composes against.

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
- **`tui/app.py`** — `_probe_provider` (match `"opencode_zen"` and pass the
  per-provider key `llm.opencode_zen_api_key` to `discovery.zen_health`),
  `_select_options` (replace `api_key=llm.api_key` with the selected provider's key,
  `getattr(llm, f"{llm.provider}_api_key", "")`), `_provider_label` (match
  `"opencode_zen"`, keep the short `"zen"` display sugar), and the
  `llm.provider == "opencode-zen"` check (~L421). See `.fledge/nest/modules.md` → `tui/`.
- **`tui/discovery.py`** — provider/fallback option lists and the
  `provider == "opencode-zen"` / `fallback == "opencode-zen"` branches
  (~L173/178/235/247) → `opencode_zen`.
- **`tests/`** — `test_config.py` (drop `api_key`; add per-provider fields +
  `.env`-loading + precedence tests), `test_llm_dispatch.py` (`opencode_zen`
  resolution + per-provider key selection), `test_app_llm_diagnostics.py` (repoint
  to `opencode_zen`), and the TUI tests `test_tui_app.py` / `test_tui_discovery.py` /
  `test_tui_screens.py` (repoint `opencode-zen` → `opencode_zen`; drop `api_key`
  references).

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
- **TUI rename + keys** — `discovery.llm_provider_options()` returns
  `["ollama", "opencode_zen"]` (and fallback options include it); no `opencode-zen`
  literal remains in `tui/`; `_provider_label("opencode_zen") == "zen"`; the TUI
  health probe/discovery read the per-provider key, not `llm.api_key`.

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
      diagnostics; `opencode-zen` no longer resolves (daemon side of PLM-005 FC-5).
- [x] AC-5: The TUI uses `opencode_zen` in its pickers, label, health probe, and
      identity handler with no `opencode-zen` literal remaining in `tui/`, and reads
      the per-provider key rather than `llm.api_key` (TUI side of PLM-005 FC-5).
- [x] AC-6: `ruff check assistant tests` and the full suite pass offline.
