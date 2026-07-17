---
id: FTHR-032
title: "Registry selection targets audio config; manifest.py defect fix"
plumage: PLM-008
status: egg
priority: P1
depends_on: [FTHR-028]
authored: 2026-07-17T15:44:56Z
agent: fledge-orchestrate/planning
fledge_version: 0.6.7
---

# FTHR-032: Registry selection targets audio config; manifest.py defect fix

## Description

Repoints the wake-model registry's selection step (`training/manifest.py select`) at the audio
surface's configuration, makes it write each selected model's **path *and* threshold** (FC-4), and
fixes a **real defect that fails today, independently of any of our work** (FC-13).

`select` is the documented final step of the wake-training workflow: after training a model, you
run it to point the runtime at that model. It has two problems this feather fixes:

1. **It targets the wrong file and crashes.** `_write_model_paths` locates a `wake:` section in
   its config target with a bare `next(i for i, ln in enumerate(lines) if ln.rstrip() == "wake:")`
   and **no fallback** (`training/manifest.py`, `_write_model_paths`). The engine's config has
   never had a `wake:` section, so this raises an **unhandled `StopIteration`** the moment `select`
   is run as documented. This is not a regression we introduce — it is broken on the current tree,
   before this plumage. It is why the wake-training workflow's last step does not run today.
2. **It writes only paths, not thresholds.** Each model's operating point lives in
   `models/wake/models.json` (`"threshold"`, set by `cmd_upsert` from the eval's
   `optimal_threshold`), but `select` writes only `wake.model_paths`. With multiple models as
   simultaneous triggers, each needs its own threshold at the runtime (FC-3) — a single shared
   threshold is wrong by construction. So `select` must write `[{path, threshold}]`.

Under the corrected architecture the write's correct destination is **`config/audio.yaml`**, which
did not exist until FTHR-028 created it — that is the whole reason this fix belongs to PLM-008 and
was deliberately left out of PLM-007 (fixing it there would have aimed it at the engine's config
and required moving it again).

**F5 is the WRITER of the hoisted wake-model schema; FTHR-029 is the reader.** The schema
(`[{path, threshold}]`) is defined in FTHR-028 (its AC-8 forbids anyone else defining it). This
feather **produces config matching that shape** — it does not define or redefine the shape. If it
cannot produce the shape, or the shape is wrong for the registry's data, that is a **finding
against FTHR-028**, not an edit that invents a competing schema here — which is exactly the
constraint that keeps this feather from colliding with FTHR-029.

**This is the one genuine test-first feather in the plumage** — the defect is real in the code as
it stands, so the test reproduces the actual `StopIteration` and is observed failing before the
fix, not a break-and-restore.

**Runs in wave 2, parallel with FTHR-029/030/031** — training-side, its own file, disjoint.

## Affected Modules

See `training/README.md` (the wake-training workflow); `models/wake/models.json` (the registry,
carrying per-model `threshold`).

- `training/manifest.py` — `CONFIG = Path("config.yaml")` (repoint to `config/audio.yaml`);
  `cmd_select` / `_write_model_paths` / `_read_model_paths` (write path+threshold; replace the
  bare `next()` with a clear error).
- `tests/` — a new test for `manifest.py select` (there is no existing test module for it; add
  one, e.g. `tests/test_manifest_select.py`). It exercises the standalone script, not the runtime.

**Files this feather must NOT touch:** anything under `hearth/audio/` (FTHR-028/029/030/031 —
this feather never touches the runtime side), the wake-model **schema definition** (FTHR-028 owns
it; produce matching config, define nothing), `config/audio.yaml`'s schema *shape* (write values
into it, do not restructure it). Staying inside `training/manifest.py` + its test holds wave 2
disjoint.

## Approach

**1. Preserve the deliberate standalone property.** `manifest.py` is stdlib-only by design — its
module docstring states it never imports the hearth runtime package, "so training has no effect on
the rest of the tree," and `cmd_select` already reads its write back with its *own* reader rather
than importing the runtime. **Keep that boundary.** Do not import `hearth.audio` or the runtime
config schema to learn the wake shape — the shape is a small documented contract
(`[{path, threshold}]`) this feather reproduces by construction. If writing the nested shape while
preserving comments genuinely needs a YAML library, adding one to the *training* dependencies is a
legitimate call to note at the gate — but importing the runtime is not.

**2. Repoint the target** from `config.yaml` to `config/audio.yaml` (FC-13). The
`HEARTH_WAKE__MODEL_PATHS` env-var escape hatch documented in the module header should be updated
in step with the new config key, or removed if the shape change makes it stale — note which at the
gate.

**3. Write path *and* threshold (FC-4).** For each selected model, read its `threshold` from
`models/wake/models.json` and write `{path, threshold}` into the audio config's wake-model list.
`vesta.onnx`'s entry has `threshold: 0.77` — that value must reach the config, not be dropped.

**4. Replace the bare `next()` with a clear, actionable error (FC-13).** When the target wake
section is absent from `config/audio.yaml`, do **not** raise `StopIteration` — emit a message that
names the missing section and the file, and how to get a valid audio config (mirroring the
`SystemExit`/`error:` style the module already uses elsewhere, e.g. `_resolve`). The absent-section
case is the one that fails today; it must become a legible instruction, not a traceback.

**5. Keep the existing round-trip self-check honest.** `cmd_select` already asserts its write
round-trips (`got == paths`); extend it to the path+threshold shape so a write bug is still caught.

## Tests

Test-first, and here step 2 is **literally true against today's code** — the defect exists now.
(1) Write the tests; (2) run against the **unchanged** `manifest.py` and observe the real failure;
(3) fix until they pass.

- `test_select_on_config_without_wake_section_raises_today_then_errors_cleanly` (new) — the honest
  reproduction. Against the **unchanged** code, running `select` with a config target that has no
  wake section raises the unhandled `StopIteration` from the bare `next()` — observe that. After
  the fix, the same case exits with a **clear, actionable error naming the section and file**, not
  a traceback. *Fails before:* raises `StopIteration` (the actual current defect). Satisfies FC-13.
- `test_select_writes_path_and_threshold_from_registry` (new) — selecting a model writes
  `{path, threshold}` into `config/audio.yaml`, with the threshold taken from `models.json`; a
  round-trip read returns the same values. Include the real `vesta` case (threshold 0.77). *Fails
  before:* only paths are written. Satisfies FC-4.
- `test_select_targets_audio_config_not_engine_config` (new) — `select` writes to
  `config/audio.yaml` and does not touch `config/engine.yaml`. *Fails before:* `CONFIG` points at
  the old `config.yaml`. Satisfies FC-13's repoint.
- `test_multiple_models_each_keep_their_own_threshold` (new) — selecting two models writes two
  entries each with its own threshold; no single shared threshold. Ties the registry fix to FC-3.
  *Fails before:* no threshold written at all.
- `test_manifest_stays_standalone` (new) — importing/executing `manifest.py` pulls in no
  `hearth.*` runtime module; the boundary the module documents is preserved after the change.
  *Fails before:* n/a if preserved — this guards the property so a fix that imports the runtime to
  learn the schema is caught.

**What a green suite proves here.** Unlike the other wave-2 feathers, this one's green suite is a
strong proof: the defect is mechanical (a crash and a missing field), fully reproducible without
hardware, and the fix is fully verifiable in CI. There is **no** "manual smoke covers the rest"
caveat for the defect itself — the honesty note here is the inverse: this is real test-first on a
real bug, and the reproduction against unchanged code is the evidence, recorded in molt as an
observed `StopIteration` before and a clean error after.

## Acceptance Criteria

- [x] AC-1: The tests listed above were observed failing before implementation and pass after
      (guard tests marked "*Fails before:* n/a" are exempt from fail-first; instead they were
      shown failing when the guarded property is deliberately violated, then pass unmodified) —
      and specifically, the absent-wake-section test was observed raising the actual
      `StopIteration` against the unchanged code (a genuine test-first cycle on a live defect, not
      a break-and-restore), recorded in molt evidence.
- [x] AC-2: `select` writes each selected model's **path and threshold** into `config/audio.yaml`,
      threshold sourced from `models/wake/models.json`; a round-trip test asserts the written
      values match the registry, including `vesta`'s 0.77 (satisfies PLM-008 FC-4).
- [x] AC-3: `select` targets `config/audio.yaml`, not the engine's config; a test asserts the
      engine config is untouched (satisfies PLM-008 FC-13's repoint).
- [x] AC-4: When the target wake section is absent, `select` emits a **clear, actionable error**
      naming the section and file and exits without a traceback — never an unhandled
      `StopIteration`; a test covers the absent case (satisfies PLM-008 FC-13).
- [x] AC-5: Multiple selected models each carry their own threshold in the written config — no
      single shared threshold (satisfies PLM-008 FC-3 from the writer side).
- [x] AC-6: `manifest.py` remains **standalone** — no import of the `hearth` runtime package after
      the change; a test guards the property. If writing the nested shape needed a YAML library, it
      was added to training deps only, noted at the gate — the runtime was not imported.
- [x] AC-7: This feather **produces** config matching FTHR-028's wake-model schema and defines no
      schema; any shape insufficiency was raised against FTHR-028, keeping this diff disjoint from
      FTHR-029 and out of `hearth/audio/`.
- [x] AC-8: Only `training/manifest.py` and its new test are added/changed, keeping wave 2 disjoint
      from FTHR-029/030/031.
- [x] AC-9: `ruff check .` is clean and the full existing test suite passes.
