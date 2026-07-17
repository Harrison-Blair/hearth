---
id: FTHR-029
title: "Wake detection: multiple models, per-model thresholds"
plumage: PLM-008
status: fledged
priority: P1
depends_on: [FTHR-028]
authored: 2026-07-17T15:37:02Z
agent: fledge-orchestrate/planning
fledge_version: 0.6.7
---

# FTHR-029: Wake detection: multiple models, per-model thresholds

## Description

Implements the real wake detector behind FTHR-028's `WakeDetector` seam: it loads the wake models
named in the audio config, scores incoming audio frames against **each model's own threshold**,
and fires when any model crosses its operating point (FC-2, FC-3).

The active set of models is **data, not code** (FC-2). The surface works with the single trained
model available today (`models/wake/vesta.onnx`) and with any number the config names — Prometheus
becomes active the day its model is trained and added to the config, with no code change. The
detector must therefore drive off the **registry/config list**, never off a hardcoded single
model; a test proves it over a synthetic multi-model set as well as the one-real-model case, the
same way PLM-007's provenance test ran over arbitrary values rather than the two real surfaces.

**This feather is the *reader* of the hoisted wake-model schema.** FTHR-028 defines the schema
(`[{path, threshold}]`, per-model, no global threshold) and FTHR-028 AC-8 forbids anyone else
defining it. This feather **owns nothing in that schema** — it reads it. If the schema turns out
insufficient for a real wake implementation, that is **a finding to raise against FTHR-028**, not
a reason to extend the schema in this feather's file, which would collide with FTHR-032 (the
writer). The seam cuts both ways: this feather also implements FTHR-028's `WakeDetector` Protocol
**as given** — if the seam is wrong, raise it against FTHR-028 rather than reshaping it from here.

**Runs in wave 2, parallel with FTHR-030/031/032.** Its files are disjoint from all three.

## Affected Modules

See `.fledge/nest/modules.md` → *veneer* (audio surface, as FTHR-028 leaves it); the wake
groundwork under `models/wake/` and `training/`.

- `hearth/audio/wake.py` (new) — the `WakeDetector` implementation: model loading, per-frame
  scoring, per-model threshold gating, multi-model fire. Uses the `wake` extra
  (`livekit-wakeword` / `onnxruntime`).
- `tests/test_audio_wake.py` (new).
- `pyproject.toml` — **only if** the audio surface must depend on the `wake` extra at runtime and
  FTHR-028 did not already wire it; prefer not to touch it (FTHR-028 owns `[project.scripts]`).
  If a dependency edge is genuinely needed here, add only that line and note it in the gate.

**Files this feather must NOT touch:** `hearth/audio/config.py` / the wake-model **schema**
(FTHR-028 owns it — read it, don't extend it), `hearth/audio/surface.py` and `stages.py`
(FTHR-028's seams — implement the Protocol in `wake.py`, don't edit the seam), the other stage
modules (FTHR-030/031), `training/manifest.py` (FTHR-032). Keeping to `wake.py` + its test is what
holds wave 2 disjoint.

## Approach

**1. Implement FTHR-028's `WakeDetector` Protocol** in `hearth/audio/wake.py`. Construct it from
the config's wake-model list — an ordered set of `{path, threshold}` — loading each model once at
startup. `models/wake/vesta.onnx` is the one trained model today (960 KB, committed); onnxruntime
loads it with no download, which is why this stage is genuinely testable in CI (unlike STT).

**2. Per-model threshold, no global (FC-3).** Each model scores independently and fires on **its
own** threshold from the config entry. There is no shared threshold anywhere — not a default, not
a fallback constant. A model with threshold 0.77 and one with 0.5 must each gate on their own
number in the same running detector. This is the correction to the stale single-`wake.threshold`
idea that CLAUDE.md still documents (FTHR-034 fixes the doc; this feather makes the code true).

**3. Multi-model fire (FC-2).** Any model crossing its threshold triggers a wake. The set is
whatever the config lists; the detector iterates it. With one entry it fires on one model; with
three it fires on any of three — **the same code path**, differing only by config length. Do not
special-case "one model" — that is the hardcoding FC-2 forbids.

**4. Scoring seam for hermetic tests.** livekit-wakeword's scoring runs on real frames; that is
fine in CI (small model, no download). But keep model *loading* and *scoring* separable enough
that a test can drive detection with **synthetic scores** for the multi-model and threshold-gating
logic — the logic under test is "does the right model fire at the right threshold," which should
not require crafting real audio that trips a real model at a precise score. Test the real
`vesta.onnx` load-and-score path too, but prove the **gating logic** against controlled scores.

**Constraints.** Reads config, defines no config schema. Implements the seam, reshapes no seam.
Match the frame format FTHR-028's source produces — if it is unclear or wrong for wake scoring,
raise it against FTHR-028. No global threshold, no single-model special case.

## Tests

Test-first: (1) write; (2) run against unchanged code, confirm each FAILS for the expected reason;
(3) implement until they pass.

- `test_wake_fires_when_a_model_crosses_its_threshold` (new) — a model scoring above its
  configured threshold fires; below, it does not. Against controlled scores. *Fails before:* no
  `wake.py`. Satisfies FC-2 (single-model case).
- `test_detection_is_driven_by_the_configured_model_set` (new) — **the data-not-code proof.**
  Parameterize over a synthetic set of **two or three** models with **distinct thresholds** and
  assert each fires on and only on its own operating point, in one running detector — then assert
  the **one-real-model** case (`vesta.onnx` alone) works by the same path. Written so a hardcoded
  single-model detector **cannot pass the multi-model parameterization**, the way PLM-007's
  provenance test ran over arbitrary values. *Fails before:* no detector. Satisfies FC-2, FC-3.
- `test_no_global_threshold_governs_detection` (new) — two models with different thresholds; a
  score that would fire under a shared/averaged threshold but must **not** fire under the correct
  per-model one (and vice versa) proves each gates on its own number, not a global. *Fails
  before:* no per-model gating. Satisfies FC-3.
- `test_real_vesta_model_loads_and_scores` (new) — the committed `vesta.onnx` loads via
  livekit-wakeword/onnxruntime and produces a score for supplied frames, proving the real
  load-and-score path, not just the gating logic. *Fails before:* no loader. (Hermetic — no
  download; the model is in-repo.)

**What a green suite proves here, and what it does not.** It proves the gating logic (which model
fires at which threshold) and that the real Vesta model loads and scores. It does **not** prove
detection **accuracy** on real speech — that a person saying "Vesta" reliably trips it and ambient
noise does not is a property of the trained model and real acoustics, verified in FTHR-033's manual
smoke, not here. Say so in molt evidence: a green wake suite is "the gating is correct and the
model loads," not "it reliably wakes on the phrase."

## Acceptance Criteria

- [x] AC-1: The tests listed above were observed failing before implementation and pass after.
- [x] AC-2: The active wake-model set is driven by the audio config; a test proves more than one
      model can be active at once with any firing, and that the detector works correctly with
      exactly one model configured — by the **same code path**, no single-model special case
      (satisfies PLM-008 FC-2).
- [x] AC-3: Each model gates on **its own** threshold from its config entry; a test proves no
      global/shared/averaged threshold governs detection (satisfies PLM-008 FC-3).
- [x] AC-4: The real committed `vesta.onnx` loads and scores via the `wake` extra in a hermetic
      test with no download (satisfies FC-2 for the model that exists today).
- [x] AC-5: This feather **reads** the wake-model schema and defines none of it; if the schema is
      insufficient it is raised as a finding against FTHR-028, not extended here — so no schema
      change lands in this feather's diff, keeping it disjoint from FTHR-032 (satisfies the
      FTHR-028 AC-8 hoist from the reader side).
- [x] AC-6: This feather implements FTHR-028's `WakeDetector` seam as given and does not modify
      `surface.py` or `stages.py`; any seam problem is raised against FTHR-028.
- [x] AC-7: Molt evidence states that a green suite proves gating and model-load, **not** wake
      accuracy on real speech (which is FTHR-033 manual smoke).
- [x] AC-8: Only `hearth/audio/wake.py` and `tests/test_audio_wake.py` are added/changed (plus at
      most a single `pyproject.toml` dependency line, noted in the gate if used), keeping wave 2
      disjoint from FTHR-030/031/032.
- [x] AC-9: `ruff check .` is clean and the full existing test suite passes.
