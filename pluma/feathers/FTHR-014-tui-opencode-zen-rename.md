---
id: FTHR-014
title: TUI opencode_zen rename
plumage: PLM-005
status: egg
priority: P2
depends_on: [FTHR-013]
authored: 2026-07-08T01:02:09Z
agent: fledge-orchestrate/planning
fledge_version: 0.2.0
---

# FTHR-014: TUI opencode_zen rename

## Description
Completes the `opencode-zen` → `opencode_zen` rename on the **TUI side**, the half
FTHR-013 deliberately left. The monitor TUI hard-codes the provider string in its
provider/fallback pickers, its identity-selection handler, and its compact display
label. This feather repoints all of them to `opencode_zen` so the TUI presents and
persists the same string the daemon now expects. Purely operator-facing strings; no
daemon/pipeline behavior changes. Satisfies the TUI half of PLM-005 FC-5; with
FTHR-013, establishes PLM-005 AC-4.

## Affected Modules
- **`tui/app.py`** — `_provider_label` (match `"opencode_zen"`, keep the short
  `"zen"` display sugar), the `name == "opencode-zen"` branch (~L358), and the
  `self._config.llm.provider == "opencode-zen"` check (~L421). Rename the matched
  string to `opencode_zen`. See `.fledge/nest/modules.md` → `tui/`.
- **`tui/discovery.py`** — the provider option list (`["ollama", "opencode-zen"]`,
  ~L173), the fallback option list (`["", "ollama", "opencode-zen"]`, ~L178), and
  the `provider == "opencode-zen"` / `fallback == "opencode-zen"` branches (~L235,
  ~L247). Rename to `opencode_zen`.
- **`tests/`** — `test_tui_app.py`, `test_tui_discovery.py`, `test_tui_screens.py`:
  repoint the `opencode-zen` literals to `opencode_zen`. **No daemon files — those
  were FTHR-013.**

## Approach
Test-first, mechanical. A pure string rename `opencode-zen` → `opencode_zen` across
`tui/` and its tests. The compact display label stays `"zen"` (display sugar,
independent of the config string) — only the *match* target changes. No behavior
beyond the string identity changes; the pickers still offer the same set, now
spelled `opencode_zen`.

## Tests
Updated (TUI unit tests; no daemon boot):
- **provider options** — `discovery.llm_provider_options()` returns
  `["ollama", "opencode_zen"]`; fallback options include `opencode_zen`; neither
  contains `opencode-zen`.
- **label** — `_provider_label("opencode_zen") == "zen"`; the old literal no longer
  maps.
- **identity pick persists** — picking the provider writes
  `("llm","provider"): "opencode_zen"`.

Fixed order: (1) update the tests to the new string; (2) confirm they FAIL against
the unchanged TUI (still emits `opencode-zen`); (3) implement until they pass.

## Acceptance Criteria
- [ ] AC-1: The tests listed above were observed failing before implementation and
      pass after.
- [ ] AC-2: The TUI's provider/fallback pickers, identity handler, and label all use
      `opencode_zen`; no `opencode-zen` literal remains in `tui/` (TUI half of
      PLM-005 FC-5).
- [ ] AC-3: `ruff check assistant tests` and the full suite pass offline.
