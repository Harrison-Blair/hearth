---
id: FTHR-034
title: "Documentation: wake-model corrections and audio-surface usage"
plumage: PLM-008
status: egg
priority: P1
depends_on: [FTHR-028, FTHR-032, FTHR-033]
authored: 2026-07-17T15:52:09Z
agent: fledge-orchestrate/planning
fledge_version: 0.6.8
---

# FTHR-034: Documentation: wake-model corrections and audio-surface usage

## Description

Makes the project's documentation tell the truth about the wake models and about the new audio
surface (FC-14). Two jobs:

1. **Correct the false wake-model claims** that FTHR-027 (PLM-007's docs feather) deliberately
   left for this plumage — its AC-8 named them and assigned them here, because the corrected facts
   depend on the audio configuration this plumage builds. Every one is false *today*, verified:
   - `CLAUDE.md:8-9` — "Wake word: **Calcifer**". Calcifer is retired; the wake words are **Vesta**
     and **Prometheus** (PLM-006, fledged).
   - `CLAUDE.md:18` — `models/wake/calcifer.onnx`, **a file that does not exist**. Only
     `models/wake/vesta.onnx` is on disk.
   - `CLAUDE.md:122-125` — `manifest.py select` "point[s] `config.yaml` at the model and set[s]
     `wake.threshold` from the manifest's optimal threshold". Stale on two counts: the target is
     now `config/audio.yaml` (FTHR-032), and there is **no single `wake.threshold`** — each model
     carries its own (FTHR-028's schema, FTHR-029's per-model gating). This is the **docs half of
     the three-place kill** on the single-threshold idea: FTHR-029 killed it in the reader,
     FTHR-032 in the writer, this feather in the docs.
   - `README.md:18-21` — claims **both** `vesta.onnx` and `prometheus.onnx` "already exist". Only
     Vesta is trained; Prometheus needs GPU training the user has not run yet.

2. **Document the audio surface** (FC-14): how it is run (`hearth-audio`), how it is configured
   (`config/audio.yaml` via the shared facility — input device, wake-model list, endpoint knobs,
   STT model/params, retry), and how a newly-trained wake model is made active (train → `manifest.py
   select` → it appears in the audio config, no code change).

**Honesty carried from the pipeline feathers.** Document what the audio surface **does today**:
it listens (wake → capture → transcribe), submits the turn, and **prints** the heard transcript
and the engine's answer. It does **not** speak — voice output is PLM-009. The docs must not
describe the finished voice assistant; they describe a listening surface whose output is text,
exactly as the plumage ships it. Overstating it here would recreate the very
docs-describe-a-different-reality problem this feather exists to fix.

**Runs in wave 4, after FTHR-033** — it documents the assembled, working surface. Depends on
FTHR-028 (the surface + config exist) and FTHR-032 (the `manifest.py select` behavior it documents
is the corrected one, not the crashing one).

## Affected Modules

See `.fledge/nest/index.md`; `training/README.md` (the wake-training workflow whose final step
FTHR-032 fixed).

- `CLAUDE.md` — `:8-9` (Calcifer wake word), `:18` (`calcifer.onnx`), `:122-125` (the
  `manifest.py select` / single-`wake.threshold` description). Plus the config-section list and
  architecture description if they need the audio surface added (check against the finished state).
- `README.md` — `:18-21` (the "both models exist" claim, in the status table and the paragraph
  under it), and the working/roadmap table (the audio listening path moves from roadmap toward
  working — state it precisely: listening lands, speaking is still roadmap).
- `training/README.md` — **only if** its description of `select` names the old config target or a
  single threshold; correct it to match FTHR-032. Check before editing.

**Do NOT touch `.fledge/`** — fledged specs and molt evidence are historical records, never
rewritten (this includes not "fixing" the pre-existing molt-format warnings on fledged feathers).
**Do NOT touch the persona lines** — FTHR-027 already corrected `CLAUDE.md:81/:88` to Vesta; they
are done, not this feather's concern.

## Approach

Work from the **finished code**, not this list — line numbers will have shifted after PLM-007 and
the earlier PLM-008 feathers landed. `grep -niI "calcifer\|prometheus\|wake.threshold\|wake_threshold"`
across `CLAUDE.md`/`README.md`/`training/README.md` is the starting point.

**What must be true after this feather:**

1. **No reference to Calcifer as the wake word**, and no reference to `calcifer.onnx` (it does not
   exist). Wake words are Vesta and Prometheus.
2. **The trained-vs-untrained status is accurate:** `vesta.onnx` is trained and on disk;
   **Prometheus is specified but not yet trained** (needs the user's GPU; becomes active when
   trained and added to the audio config, with no code change — the data-not-code property
   FTHR-029 implements). Do not claim `prometheus.onnx` exists.
3. **No claim of a single shared wake threshold.** Each model has its own, in `config/audio.yaml`;
   `manifest.py select` writes per-model path+threshold there. Correct `CLAUDE.md:122-125`
   accordingly.
4. **The audio surface is documented:** `hearth-audio` as a run target; `config/audio.yaml` as its
   config; the wake-model list, endpoint, and STT settings as its knobs; activating a new model via
   `select`. Framed as **listening only, output is text, no voice yet (PLM-009)**.
5. **The working/roadmap table reflects reality:** listening (wake/VAD/STT → printed answer) has
   landed; speaking (TTS/voice output) is still roadmap.

**Constraint.** Prose only (plus possibly the README table). Do not overstate: listening ships,
speaking does not. Do not touch `.fledge/` or the persona lines. If a doc claim is genuinely
uncertain against the finished code, verify it in the code rather than guessing — the whole point
of this feather is docs that match reality.

## Tests

**No unit tests for prose — inventing one would be theatre**, the same honest position as FTHR-027.
Nothing in `pytest` asserts on `CLAUDE.md`/`README.md` content, and a keyword grep pins a word, not
the truth of the sentence around it. What is mechanically verifiable, and must be recorded as molt
evidence:

- **`grep -niI "calcifer" CLAUDE.md README.md training/README.md` returns nothing** — the wake word
  and the non-existent `calcifer.onnx` are gone. (The persona-line Calcifers were already removed by
  FTHR-027; if any remain, that is a FTHR-027 regression to flag, not silently absorb here.)
- **No doc claims `prometheus.onnx` exists** — grep `prometheus` and confirm every hit describes it
  as specified/untrained/future, never as an on-disk model.
- **No doc claims a single `wake.threshold`** — grep `wake.threshold` / `wake_threshold` and confirm
  none survives as a runtime-facing claim.
- **The audio-surface run/config instructions are executed as written** where runnable (e.g.
  `hearth-audio --help` or equivalent resolves; `config/audio.yaml` is where the doc says). A
  documented command that does not run is the FTHR-027 AC-3 lesson — a stale instruction fails in a
  user's hands, so any command the docs give must be one that works.
- The existing test suite still passes (docs-only change; nothing should break, but confirm).

## Acceptance Criteria

- [ ] AC-1: `grep -niI calcifer` over `CLAUDE.md`, `README.md`, and `training/README.md` returns
      nothing; no doc names Calcifer as the wake word or references `calcifer.onnx`. Recorded as
      molt evidence (satisfies PLM-008 FC-14; discharges FTHR-027 AC-8's deferral).
- [ ] AC-2: Documentation states which wake models are **trained** (`vesta.onnx`) and which are
      **specified but not yet trained** (Prometheus); no doc claims `prometheus.onnx` exists on disk
      (satisfies PLM-008 FC-14).
- [ ] AC-3: No documentation claims a single shared `wake.threshold`; the docs describe per-model
      thresholds in `config/audio.yaml` written by `manifest.py select` — the docs half of the
      three-place correction (satisfies PLM-008 FC-14).
- [ ] AC-4: Documentation describes running the audio surface (`hearth-audio`), configuring it
      (`config/audio.yaml`: input device, wake-model list, endpoint, STT), and activating a
      newly-trained model via `select`; any command given is executed as written and works
      (satisfies PLM-008 FC-14).
- [ ] AC-5: The docs describe the audio surface as **listening only — output is printed text, no
      voice output** — with speaking explicitly noted as PLM-009 roadmap; nothing overstates it as a
      finished voice assistant.
- [ ] AC-6: `.fledge/` is untouched, and the persona lines FTHR-027 already fixed
      (`CLAUDE.md:81/:88`) are not re-edited — this feather owns the wake-model and audio-usage
      docs only.
- [ ] AC-7: `ruff check .` is clean and the full existing test suite passes (docs-only change).
