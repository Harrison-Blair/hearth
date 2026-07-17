---
id: FTHR-022
title: Shared config facility and per-component config directory
plumage: PLM-007
status: fledged
priority: P0
depends_on: []
authored: 2026-07-17T08:03:06Z
agent: fledge-orchestrate/planning
fledge_version: 0.6.7
---

# FTHR-022: Shared config facility and per-component config directory

## Description

Turns configuration loading from an engine-only mechanism into a **shared, parameterized
facility**, and moves configuration into a per-component directory. Satisfies PLM-007 FC-10
(shared loading mechanism), FC-9 in part (the directory and the engine's own file; the chat
veneer's file arrives in FTHR-024), and FC-14 (the release binary still finds its config).

Today `hearth/config.py` hardcodes one file (`config.yaml`) for one component. The chat veneer
will need the identical behavior — path resolution, active/reference pattern, `HEARTH_*` env
overrides, fail-loud on absence — against a *different* file. This feather makes that behavior
take the file as a parameter instead of assuming it, and moves the engine's own config into the
directory that will hold every component's.

**This feather ships no user-visible change.** The engine runs as before, reads the same
settings, and builds the same binary. Its value is that after it lands, a second component's
config is a call to an existing facility rather than a second copy of the loader.

**Scoped deliberately narrow:** it does *not* rename `veneer:` to `gateway:` or remove
anything. It **adds** `gateway: {host, port}` to the engine's file. The old `veneer:` section
stays until FTHR-024 removes it — that feather owns FC-11/FC-12. Leaving both present briefly
is what lets this feather run in parallel with FTHR-023 without either touching the other's
files.

## Affected Modules

See `.fledge/nest/modules.md` → *config*; `.fledge/nest/architecture.md` → *configuration model*.

- `hearth/config.py` — the loader. `resolve_config_path()` (currently hardcodes
  `CONFIG_YAML_PATH`) and `Settings.settings_customise_sources()` (currently calls it with no
  argument) are the two functions this feather generalizes.
- `config/engine.yaml` (new; moved from `config.yaml`)
- `config/defaults/engine.yaml` (new; moved from `default-config.yaml`)
- `packaging/build.sh` — line 28's `--add-data "$(pwd)/config.yaml:."` must land the config
  where the resolver looks inside a frozen bundle.
- `tests/test_config.py`

**Files this feather must NOT touch** (they belong to FTHR-023, which runs concurrently):
`hearth/app.py`, `hearth/veneer/**`, `tests/test_veneer*.py`. The engine keeps reading
`settings.veneer` for its bind address; repointing it at `settings.gateway` is FTHR-024's job.

## Approach

**1. Parameterize the resolver.** `resolve_config_path()` grows a component parameter (e.g.
`resolve_config_path(component: str) -> Path`) and derives its filename from it. The resolution
order and its rationale are preserved exactly as documented in the existing docstring — only
the target filename becomes a variable:

1. `HEARTH_CONFIG` env var, if set, must point at an existing file (unchanged; still engine-only
   — a per-component override env var is **not** in scope, no one has asked for one).
2. The package-adjacent `config/<component>.yaml` — a source checkout, and also the PyInstaller
   bundle root.
3. `./config/<component>.yaml` relative to the working directory.
4. Otherwise raise `FileNotFoundError` naming both paths searched and the reference file to copy.

Keep the module-level path constant that `tests/test_config.py` monkeypatches
(`hearth.config.CONFIG_YAML_PATH`) or replace it with an equivalent seam — either is fine, but
the tests must retain a way to redirect resolution at a `tmp_path` without touching the real
filesystem. Do not make the tests reach the repo's actual config.

**2. Move the files.** `git mv config.yaml config/engine.yaml`, `git mv default-config.yaml
config/defaults/engine.yaml`. Use `git mv` so history follows. The active/reference pair keeps
its existing relationship: `config/defaults/engine.yaml` is the documented reference with a
comment per field; `config/engine.yaml` is what loads. `.gitignore` may need the moved active
file's path updating — check before assuming.

**3. Add `gateway:` to the engine's file.** `gateway: {host: 127.0.0.1, port: 8765}` in both
`config/engine.yaml` and `config/defaults/engine.yaml`, with a `GatewayConfig` model on
`Settings`. It is unused this feather — FTHR-024 repoints `app.py` at it. Add it here anyway so
the section exists before two dependents need it. Do **not** remove `veneer:`.

**4. Realign packaging.** `--add-data "$(pwd)/config.yaml:."` currently lands the file at the
bundle root because that is where the resolver's package-adjacent path points. After the move
the resolver looks for `config/engine.yaml`, so the bundled data must land under a `config/`
subdirectory of the bundle root — `--add-data "$(pwd)/config/engine.yaml:config"` or
equivalent. **Verify this against the resolver rather than reasoning about it**: build the
binary and run it (see Tests). This is the one part of this feather that a unit test cannot
fully prove, and the part with the largest blast radius.

**Constraints.** No secret fields in the YAML — `.env` only, per FTHR-015 (`CLAUDE.md` §
Configuration model). This is a mechanical generalization: no new settings beyond `gateway:`,
no behavior change, no restructuring of the schema.

## Tests

Test-first, in this order: (1) write these tests; (2) run against unchanged code and confirm
each FAILS for the expected reason — not an import error standing in for a real assertion;
(3) implement until they pass.

In `tests/test_config.py`. The existing tests there already pin the precedence chain and must
keep passing, updated only where they name the moved file:

- `test_config_loads_yaml_base` … `test_no_config_anywhere_fails_loud` (existing) — retarget the
  `config_yaml` fixture at `config/engine.yaml`. *Fails before:* fixture points at the old path.
- `test_resolver_targets_named_component_file` (new) — the facility, given a component name,
  resolves `config/<component>.yaml`. Parameterize over at least two component names so the
  test proves the filename is a **variable, not a branch**. This is the feather's whole point
  and the AC-3 evidence. *Fails before:* `resolve_config_path()` takes no argument.
- `test_missing_component_config_fails_loud` (new) — a component whose file is absent raises
  `FileNotFoundError` naming the searched paths, not a silent empty load. Pins FC-10's
  fail-loud clause for the *shared* facility, not just the engine. *Fails before:* the message
  names `config.yaml` unconditionally.
- `test_engine_config_exposes_gateway_section` (new) — `settings.gateway.host/.port` load from
  the engine's file. *Fails before:* no `gateway` attribute on `Settings`.
- `test_default_persona_prompt_*` (existing, 4 tests) — these read `default-config.yaml` via a
  hardcoded relative path (`tests/test_config.py:144`). Update that path to
  `config/defaults/engine.yaml`. They will fail with `FileNotFoundError` if missed, so the move
  is self-policing here — but do not let that be the *only* thing checking the reference file
  moved.

**The packaging check (AC-6) is not a unit test.** Run `make release` and execute the produced
`dist/hearth-$(uname -m)` far enough to prove it resolves its config — the existing release
smoke check is the model; keep its intent. Record the command run and its output as molt
evidence. A green `pytest` proves nothing about the frozen bundle: the source tree's `config/`
is present in a checkout whether or not `--add-data` is right.

## Acceptance Criteria

- [x] AC-1: The tests listed above were observed failing before implementation and pass after.
- [x] AC-2: `config.yaml` has moved to `config/engine.yaml` and `default-config.yaml` to
      `config/defaults/engine.yaml`, both via `git mv`; no config file remains at the repo root
      (satisfies PLM-007 FC-9 for the engine).
- [x] AC-3: Config loading is provided by one facility that takes the component as a parameter;
      a test proves it resolves a named component's file for more than one component name, so
      the second caller (the chat veneer) needs no second loader (satisfies PLM-007 FC-10).
- [x] AC-4: The facility's resolution order and fail-loud behavior are unchanged in substance
      from today's documented order, and a test covers a missing component config raising a
      `FileNotFoundError` that names the paths searched (satisfies PLM-007 FC-10).
- [x] AC-5: `config/engine.yaml` and `config/defaults/engine.yaml` carry a `gateway:` section
      with `host` and `port`, loadable as `settings.gateway`; the existing `veneer:` section is
      still present and unchanged.
- [x] AC-6: `make release` builds and the resulting binary resolves its configuration when run
      outside the source tree; the command and its output are recorded as molt evidence
      (satisfies PLM-007 FC-14). Evidence must show the **frozen binary** loading config — a
      passing test suite does not satisfy this criterion.
- [x] AC-7: No secret-bearing field was added to either YAML file (FTHR-015's rule).
- [x] AC-8: `hearth/app.py`, `hearth/veneer/**`, and `tests/test_veneer*.py` are untouched by
      this feather, leaving FTHR-023 free to run concurrently.
- [x] AC-9: `ruff check .` is clean and the full existing test suite passes.
