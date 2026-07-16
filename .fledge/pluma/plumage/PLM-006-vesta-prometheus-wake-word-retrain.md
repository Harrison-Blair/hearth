---
id: PLM-006
title: "Vesta & Prometheus wake-word retrain"
status: fledged
priority: P1
authored: 2026-07-16T02:40:35Z
agent: fledge-orchestrate/planning
fledge_version: 0.5.5
---

# PLM-006: Vesta & Prometheus wake-word retrain

## Context
Companion to PLM-005 (Vesta persona rework), which covers only the assistant's text/voice identity. This plumage covers the assistant's audio **wake word**, currently "Calcifer" via `training/calcifer.yaml` and `models/wake/calcifer.onnx`. The user wants Calcifer retired entirely and replaced with two candidate wake words, both wired as valid simultaneous triggers: **"Vesta"** (matching the persona) and **"Prometheus"** (a separate, purely acoustic choice — not a persona identity; PLM-005 fixes the persona character as "Vesta" regardless of wake word).

The wake-word pipeline (`training/`) is entirely separate from the runtime: its own isolated `.venv-train` (ROCm torch + livekit-wakeword), its own synthetic-data workflow, no automated test suite (verified via `.fledge/nest/domain.md`'s own open questions), and verified by an FPPH/recall gate (`manifest.py`'s `gate_passed`) rather than pytest. Critically, **neither `config.yaml` nor `default-config.yaml` has a `wake` section at all** (confirmed by grep — zero hits) — the runtime does not consume any wake-word model today, so this plumage is training-pipeline-only; nothing in the daemon changes.

Production training (25k samples, 100k steps) requires a specific ROCm-capable GPU (RX 9070 XT / RDNA4·gfx1201) and is long-running — not something to gamble on an automated implementer's sandboxed environment. This plumage therefore stops at proving the renamed pipeline works via each config's fast `--smoke` run; the user runs the real production training themselves afterward using the shipped configs.

## User Stories
- As the assistant's user, I want "Calcifer" retired as a wake word entirely — including its trained artifact and manifest entry, not just the config files — so that no trace of it remains anywhere under `training/` or `models/wake/`.
- As the assistant's user, I want dedicated, hand-curated training configs for both "Vesta" and "Prometheus," so that when I run production training myself, both wake words get equal-quality adversarial-negative tuning (not one hand-tuned and one auto-generated).
- As the assistant's user, I want the pipeline's plumbing (scripts, defaults, README) to actually work end-to-end for both new phrases before I invest GPU time in a production run, so that I'm not debugging config/script issues mid-training.

## Functional Criteria
1. FC-1: `training/calcifer.yaml` is renamed to `training/vesta.yaml`: `model_name`/`target_phrases` set to `vesta`, Calcifer-specific `custom_negative_phrases` replaced with a hand-curated list of Vesta-appropriate near-miss phonemes (1-2 phoneme edits, not near-identical, matching the existing list's style), and all Calcifer-referencing comments updated.
2. FC-2: A new `training/prometheus.yaml` is authored (same structure/knobs as `vesta.yaml`: data generation, TTS, augmentation, model architecture, training hyperparameters), with `model_name`/`target_phrases` set to `prometheus` and its own hand-curated `custom_negative_phrases` list of Prometheus-appropriate near-miss phonemes.
3. FC-3: `train.py`'s `--config` CLI argument becomes required (no default), so no phrase is silently implied as primary.
4. FC-4: `train_batch.py`'s `BASE_CONFIG` constant points at `training/vesta.yaml` (the template-of-record for any future phrase added via `phrases.txt`; neither Vesta nor Prometheus uses this batch/auto-negative path since both have dedicated configs).
5. FC-5: `README.md`'s wake-word-specific lines (currently "Wake word (Calcifer)" and the `models/wake/calcifer.onnx` path) are updated to name both wake words and both model paths (`models/wake/vesta.onnx`, `models/wake/prometheus.onnx`).
6. FC-6: `training/README.md`'s Calcifer-specific instructions/examples are updated to reflect the renamed default config and the two-phrase setup (e.g. the "Default phrase: Calcifer" line, example commands referencing `calcifer.yaml`).
7. FC-7: Running `train.py --smoke --config training/vesta.yaml` and `train.py --smoke --config training/prometheus.yaml` each completes successfully, produces `models/wake/vesta_smoke.onnx` / `models/wake/prometheus_smoke.onnx`, and each appears as an entry in `models/wake/models.json` (verified via `manifest.py list`) — proving the renamed pipeline's plumbing works end-to-end for both phrases. The production run (full sample/step counts) is explicitly not run by this plumage's implementation.
8. FC-8: The legacy Calcifer wake-word artifact is fully retired: `models/wake/calcifer.onnx` is deleted, and its `"calcifer"` entry is removed from `models/wake/models.json`. `manifest.py` currently has no removal subcommand (only `upsert`/`list`/`regen`/`select`) — a `remove <slug>` subcommand (mirroring `upsert`'s shape: loads the manifest, deletes the key, saves) is added to `manifest.py` and used to perform the removal, rather than hand-editing the JSON, so future cleanups have a real mechanism.

## Acceptance Criteria
- [x] AC-1: `training/vesta.yaml` exists with `model_name`/`target_phrases` = `vesta` and Vesta-specific curated negative phrases; `training/calcifer.yaml` no longer exists (FC-1).
- [x] AC-2: `training/prometheus.yaml` exists with `model_name`/`target_phrases` = `prometheus`, Prometheus-specific curated negative phrases, and matches `vesta.yaml`'s structure/knobs (FC-2).
- [x] AC-3: `train.py --config` is a required argument with no default value (FC-3).
- [x] AC-4: `train_batch.py`'s `BASE_CONFIG` resolves to `training/vesta.yaml` (FC-4).
- [x] AC-5: `README.md` names both "Vesta" and "Prometheus" as wake words with both model paths; no remaining "Calcifer" wake-word reference (FC-5).
- [x] AC-6: `training/README.md` contains no remaining reference to `calcifer.yaml` or "Calcifer" as the default/example phrase (FC-6).
- [x] AC-7: Both smoke runs (`vesta.yaml`, `prometheus.yaml`) complete successfully, produce their respective `*_smoke.onnx` files, and both are listed by `manifest.py list` (FC-7).
- [x] AC-8: No occurrence of "calcifer"/"Calcifer" remains anywhere under `training/` (configs, scripts, README) or `models/wake/` (artifacts + manifest entries).
- [x] AC-9: `models/wake/calcifer.onnx` no longer exists on disk and `models/wake/models.json` has no `"calcifer"` key; `manifest.py` gained a `remove <slug>` subcommand used to perform the removal (FC-8).

## Out of Scope
- Wiring live wake-word detection into the running daemon (`hearth run`) — no `hearth/wake/` module exists today; neither `config.yaml` nor `default-config.yaml` has a `wake` section, and this plumage does not add one. Runtime behavior is entirely unchanged.
- Running the actual production training (25k samples / 100k steps) for either phrase — requires the user's specific ROCm GPU hardware and is long-running; left as a manual step for the user after this plumage ships the configs.
- Any change to `hearth/persona.py`, `hearth/config.py`, or PLM-005's persona-prompt content — this plumage touches only `training/` and the wake-word-specific portions of `README.md`.
- Deciding a final single wake word between Vesta/Prometheus — both are trained as genuinely simultaneous alternate wake words per the user's decision during interrogation, not a bake-off with one winner.

## Open Questions
None outstanding — all decision points raised during interrogation were resolved with the user.
