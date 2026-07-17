---
id: FTHR-031
title: Offline transcription via faster-whisper
plumage: PLM-008
status: egg
priority: P1
depends_on: [FTHR-028]
authored: 2026-07-17T15:42:46Z
agent: fledge-orchestrate/planning
fledge_version: 0.6.7
---

# FTHR-031: Offline transcription via faster-whisper

## Description

Implements the real transcriber behind FTHR-028's `Transcriber` seam: it turns a captured
utterance into text, offline, with faster-whisper (FC-6). The model and its parameters are
configuration; the defaults are the ones proven in the user's stenographer project —
`Systran/faster-distil-whisper-medium.en`, compute type `int8`, beam size 5, English.

**This feather carries an explicit, user-made decision about what its tests prove, and it must
not quietly widen it back.** faster-whisper's default model is ~800 MB, downloaded on first use.
Running it for real in CI would mean a large download, slow tests, and a network dependency in a
suite that is otherwise fully hermetic. The user chose (PLM-008 decomposition Q4=A) to **mock at
the faster-whisper library boundary in CI**: the hermetic tests prove that the configured values
reach the library and that the returned transcript flows onward to the engine — they do **not**
prove the model transcribes audio correctly. Real audio-to-text is FTHR-033's manual smoke, where
a model download is acceptable. **AC-4 states this narrowing in its own words**; nothing in this
feather may imply CI is testing transcription accuracy.

**Runs in wave 2, parallel with FTHR-029/030/032.** Files disjoint. Reads STT config from
FTHR-028's audio config, defines no schema; implements FTHR-028's `Transcriber` seam as given —
seam or config-shape problems are findings against FTHR-028, not reshaping from here.

## Affected Modules

See `.fledge/nest/modules.md` → *veneer* (audio surface, as FTHR-028 leaves it). External
reference (the proven defaults): the user's stenographer project's ASR config
(`Systran/faster-distil-whisper-medium.en`, `int8`, beam 5, English).

- `hearth/audio/transcribe.py` (new) — the `Transcriber` implementation: construct a
  faster-whisper model from config, transcribe an utterance, return text. Uses the `stt` extra
  (`faster-whisper`).
- `tests/test_audio_transcribe.py` (new) — mocks at the faster-whisper boundary.
- `pyproject.toml` — only if a runtime dependency edge on the `stt` extra is genuinely needed and
  FTHR-028 did not wire it; if so, **one line, noted at the gate** (same bounded carve-out as
  FTHR-029/030).

**Files this feather must NOT touch:** `surface.py` / `stages.py` (implement the
Protocol in `transcribe.py`, don't edit the seam), the other stage modules (FTHR-029/030),
`training/manifest.py` (FTHR-032). Staying in `transcribe.py` + its test holds wave 2 disjoint.

> **Orchestrator amendment (2026-07-17, PLM-008 resume):** the AC-7 schema-insufficiency escape
> hatch fired. FTHR-028's `STTConfig` carried only `model` (default `"base"`) and `language`, but
> FC-6/AC-2 require `compute_type` and `beam_size` to be configuration too, with the stenographer
> defaults. Per user decision (option A), this feather is authorized to make the **minimal**
> `STTConfig` schema addition in `hearth/audio/config.py`: add `compute_type` (default `"int8"`)
> and `beam_size` (default `5`), and correct the `model` default to
> `"Systran/faster-distil-whisper-medium.en"`. That single class is the only permitted edit to
> `config.py` — do not restructure the file or touch any other config section. AC-7/AC-8 below are
> amended to match.

## Approach

**1. Implement FTHR-028's `Transcriber` Protocol** in `hearth/audio/transcribe.py`. Construct the
faster-whisper model from config — model name, compute type, beam size, language — and transcribe
the captured utterance to a string.

**2. The config carries the stenographer-proven defaults (FC-6):**
`Systran/faster-distil-whisper-medium.en`, `int8`, beam size 5, English. These are **defaults in
config**, tunable on the Pi without code (the Pi may need a lighter model — that is the recorded
Open Question, and config is exactly what lets it change without a code edit). **Only these four
parameters** — nothing about lazy loading, idle-unload, or model lifecycle, which the user
explicitly excluded when scoping PLM-008. The model is constructed and used; no residency policy.

**3. Mock at the faster-whisper boundary — and prove the config actually reaches it (the crux of
Q4=A).** The seam is the faster-whisper model object / its constructor. Tests inject or patch that
boundary so **no real model loads or downloads**, and assert two things:
- the **configured values are passed to the library** — a wrong `model`/`compute_type`/`beam_size`
  /`language` in config is caught because the test sees what reached the constructor/call. This is
  what makes the mock prove *wiring* rather than prove nothing.
- the **transcript the library returns flows onward** — the string the (faked) model produces is
  what the surface submits as the turn.

Mocking the boundary without asserting the config reached it would be a hollow test — it would pass
against a transcriber that ignored config entirely. The assertion on the passed values is the
whole point.

**4. Match the audio format faster-whisper expects** against what FTHR-028's source/endpointer
produce (sample rate, dtype). A mismatch is a finding against FTHR-028's seam, not an invented
conversion here.

**Constraints.** Reads config, defines no schema. Implements the seam, reshapes no seam. No model
lifecycle/lazy-loading (explicitly out of scope). The real model never loads in CI.

## Tests

Test-first: (1) write; (2) run against unchanged code, confirm each FAILS for the expected reason;
(3) implement until they pass. All mock the faster-whisper boundary — no download, no real model.

- `test_configured_model_params_reach_faster_whisper` (new) — **the Q4=A crux.** With the
  faster-whisper boundary faked, assert the config's `model`, `compute_type`, `beam_size`, and
  `language` are exactly what reach the library constructor/transcribe call. A wrong config value
  is caught here. *Fails before:* no `transcribe.py`. Satisfies FC-6's "parameters are
  configuration."
- `test_returned_transcript_flows_to_the_turn` (new) — the (faked) model returns known text; the
  transcriber returns that text for submission as the turn. Proves the transcript reaches the
  engine path. *Fails before:* no transcriber.
- `test_no_real_model_loads_in_ci` (new) — the test path constructs no real faster-whisper model
  and triggers no download; the boundary is faked throughout. Guards the hermetic property
  explicitly, so a later edit that accidentally instantiates the real model is caught. *Fails
  before:* if the implementation loads the model eagerly at import.
- `test_no_model_lifecycle_management` (new) — asserts the transcriber holds no lazy-load /
  idle-unload / residency policy (the thing the user cut from FC-6 during scoping); it constructs
  and uses the model, nothing more. Prevents the excluded feature creeping back. *Fails before:*
  n/a if absent — this pins scope, and would fail if lifecycle code were added.

**What a green suite proves here, and what it explicitly does NOT.** It proves the **wiring**: the
configured model and parameters reach faster-whisper, and the returned transcript flows to the
turn. It does **NOT** prove faster-whisper transcribes audio correctly — no real model runs in CI,
by the user's decision. Real supplied-audio-to-expected-text is FTHR-033's manual smoke. This
distinction is not incidental; it is the decision Q4=A made, and molt evidence must record a green
run as "config reaches the library and the transcript flows," never as "transcription works."

## Acceptance Criteria

- [x] AC-1: The tests listed above were observed failing before implementation and pass after.
      Guard tests marked "*Fails before:* n/a" are exempt from the fail-first requirement;
      instead they were shown failing when the guarded property is deliberately violated, then
      pass unmodified.
- [x] AC-2: The transcriber turns a captured utterance into text via faster-whisper, with the
      model and parameters (`Systran/faster-distil-whisper-medium.en`, `int8`, beam 5, English as
      defaults) taken from the audio config; a test asserts those values reach the library
      (satisfies PLM-008 FC-6).
- [x] AC-3: The resulting transcript flows onward for submission as the engine turn; a test proves
      the returned text is what the surface submits.
- [x] AC-4: **The test strategy's boundary is explicit in the feather and its evidence: CI mocks
      the faster-whisper library, proving config plumbing reaches it and the transcript flows —
      it does NOT prove transcription accuracy, which is FTHR-033's manual smoke.** No test in this
      feather implies the model transcribes correctly, and molt evidence records a green run as
      wiring-proven, not accuracy-proven (honors decomposition Q4=A).
- [x] AC-5: No real faster-whisper model loads or downloads in CI; a test guards the hermetic
      property so an accidental eager instantiation is caught.
- [x] AC-6: The transcriber holds **no model-lifecycle policy** (no lazy loading, idle-unload, or
      residency) — that was explicitly excluded when PLM-008 was scoped; a test pins its absence.
- [x] AC-7: This feather implements FTHR-028's `Transcriber` seam as given and leaves
      `surface.py`/`stages.py` unchanged. Per the orchestrator amendment above, it makes the
      **minimal** `STTConfig` schema addition in `hearth/audio/config.py` (add `compute_type` and
      `beam_size`, correct the `model` default) — that single class only, no other config section
      or file restructured — so FC-6's four configurable params are real configuration.
- [x] AC-8: Only `hearth/audio/transcribe.py`, `tests/test_audio_transcribe.py`, and the
      minimal `STTConfig` addition in `hearth/audio/config.py` are added/changed (plus at most a
      single noted `pyproject.toml` dependency line), keeping wave 2 disjoint from FTHR-029/030/032.
- [x] AC-9: `ruff check .` is clean and the full existing test suite passes.
