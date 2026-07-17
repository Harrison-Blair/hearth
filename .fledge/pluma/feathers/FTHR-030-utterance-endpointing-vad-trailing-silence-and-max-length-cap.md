---
id: FTHR-030
title: "Utterance endpointing: VAD trailing-silence and max-length cap"
plumage: PLM-008
status: egg
priority: P1
depends_on: [FTHR-028]
authored: 2026-07-17T15:39:59Z
agent: fledge-orchestrate/planning
fledge_version: 0.6.7
---

# FTHR-030: Utterance endpointing: VAD trailing-silence and max-length cap

## Description

Implements the real endpointer behind FTHR-028's `Endpointer` seam: after a wake word fires, it
consumes captured frames and decides **when the user has stopped speaking**, so the utterance can
be handed to transcription (FC-5). The policy is a **trailing-silence timeout** — end the
utterance after a configurable run of continuous non-speech — **bounded by a configurable
maximum utterance length**, so a stuck-open or noisy mic cannot capture forever.

Speech/non-speech per frame comes from `webrtcvad` (the `vad` extra). The **decision policy on top
of it** — how much trailing silence ends a turn, the max cap, VAD aggressiveness — is this
feather's substance, and it is all configuration (the knobs `default-config.yaml` already
anticipated). `webrtcvad` is a small native extension with no model download, so this stage's real
per-frame path is genuinely testable in CI.

**Runs in wave 2, parallel with FTHR-029/031/032.** Its files (`hearth/audio/endpoint.py` + test)
are disjoint from all three. It **reads** endpoint config keys from FTHR-028's audio config and
**implements FTHR-028's `Endpointer` Protocol as given** — if the seam or the config shape is
wrong for real endpointing, that is a finding to raise against FTHR-028, not a reshaping from here
(same discipline as FTHR-029).

## Affected Modules

See `.fledge/nest/modules.md` → *veneer* (audio surface, as FTHR-028 leaves it);
`default-config.yaml` documents VAD aggressiveness as an intended knob.

- `hearth/audio/endpoint.py` (new) — the `Endpointer` implementation: per-frame VAD, the
  trailing-silence state machine, the max-length cap. Uses `webrtcvad`.
- `tests/test_audio_endpoint.py` (new).
- `pyproject.toml` — only if a runtime dependency edge on the `vad` extra is genuinely needed and
  FTHR-028 did not wire it; if so, **one line, noted at the gate** (the same bounded carve-out as
  FTHR-029 AC-8). Note `vad` pins `setuptools<81` — do not disturb that pin.

**Files this feather must NOT touch:** `hearth/audio/config.py` / the audio config **schema**
(FTHR-028 owns it — read the endpoint keys, define none), `surface.py` / `stages.py` (implement
the Protocol in `endpoint.py`, don't edit the seam), the other stage modules (FTHR-029/031),
`training/manifest.py` (FTHR-032). Staying in `endpoint.py` + its test holds wave 2 disjoint.

## Approach

**1. Implement FTHR-028's `Endpointer` Protocol** in `hearth/audio/endpoint.py`. It accepts frames
after a wake fires and signals when the utterance is complete; the exact method shape is whatever
FTHR-028 defined — adapt to it.

**2. The policy — a trailing-silence state machine (FC-5).** Track continuous non-speech; when it
reaches the configured trailing-silence duration, end the utterance and return what was captured.
Speech resets the silence run. All three of {VAD aggressiveness, trailing-silence duration, max
length} are config-driven — no magic numbers in code.

**3. The max-length cap (FC-5, the safety bound).** Independently of silence, if the utterance
reaches the configured maximum length, end it. This is the "silence never arrives" guard — a mic
stuck open on a noisy room must not capture indefinitely. It is a *separate* termination reason
from trailing-silence and must be tested separately (AC-3), because it is the one that only fires
when the normal path fails.

**4. webrtcvad per-frame, policy on top.** `webrtcvad` classifies a frame as speech/non-speech at
a chosen aggressiveness; it requires specific frame durations and sample rates — respect them and
match the frame format FTHR-028's source produces (if they are incompatible, that is a finding
against FTHR-028's source seam, not something to paper over with resampling invented here).

**5. Keep VAD classification injectable for the policy tests.** As with wake's gating tests, the
*policy* (silence counting, cap) is what has bugs, and it should be provable against a controlled
speech/non-speech sequence without crafting real audio that a real VAD happens to classify a
precise way. Test the real `webrtcvad` path too (AC-4), but prove the state machine against a
supplied classification stream.

**Constraints.** Reads config, defines no schema. Implements the seam, reshapes no seam. No global
constants for the timings. Do not disturb the `setuptools<81` pin the `vad` extra carries.

## Tests

Test-first: (1) write; (2) run against unchanged code, confirm each FAILS for the expected reason;
(3) implement until they pass.

- `test_utterance_ends_after_trailing_silence` (new) — a controlled speech-then-silence stream
  ends the utterance after exactly the configured silence duration, not before; captured audio is
  the speech up to the endpoint. *Fails before:* no `endpoint.py`. Satisfies FC-5 (silence path).
- `test_speech_resets_the_silence_run` (new) — silence shorter than the threshold, followed by
  more speech, does **not** end the utterance; only a full continuous silence run does. Guards the
  state machine against ending on a mid-sentence pause. *Fails before:* no state machine.
- `test_max_length_cap_terminates_when_silence_never_arrives` (new) — **the safety-bound test.** A
  stream that never goes silent (continuous speech/noise) is terminated at the configured maximum
  length, with the cap as the termination reason. This fires only when the normal silence path
  does not, which is why it is separate. *Fails before:* no cap. Satisfies FC-5 (bound).
- `test_config_drives_all_three_knobs` (new) — aggressiveness, trailing-silence duration, and max
  length all come from the audio config; changing each changes behavior. Proves no magic numbers.
  *Fails before:* values hardcoded.
- `test_real_webrtcvad_classifies_frames` (new) — real `webrtcvad` classifies supplied frames at
  the configured aggressiveness and frame format, proving the real per-frame path (not just the
  policy). *Fails before:* no VAD integration. (Hermetic — native lib, no download.)

**What a green suite proves, and what it does not.** It proves the endpointing **policy** (silence
counting, reset, cap) and that real `webrtcvad` classifies frames. It does **not** prove the
chosen silence/aggressiveness values feel right to a human mid-conversation — whether the endpoint
lands where a real speaker expects — which is a tuning judgment on the Pi, verified in FTHR-033's
manual smoke and adjustable by config. Say so in molt evidence: green means "the policy is
correct," not "the timings are well-tuned for real speech."

## Acceptance Criteria

- [ ] AC-1: The tests listed above were observed failing before implementation and pass after.
- [ ] AC-2: Utterance capture ends after a **configurable trailing-silence** period; a test proves
      it ends at the configured duration and that mid-utterance pauses shorter than it do not end
      the turn (satisfies PLM-008 FC-5).
- [ ] AC-3: A **configurable maximum utterance length** terminates capture when silence never
      arrives; a separate test covers this bound firing independently of the silence path
      (satisfies PLM-008 FC-5).
- [ ] AC-4: Real `webrtcvad` classifies frames at the configured aggressiveness in a hermetic test
      with no download (satisfies FC-5's speech-detection basis).
- [ ] AC-5: VAD aggressiveness, trailing-silence duration, and max length are all read from the
      audio config with no hardcoded timings; a test proves each knob drives behavior.
- [ ] AC-6: This feather **reads** endpoint config keys and defines **no** config schema; any
      schema insufficiency is raised against FTHR-028, keeping this diff disjoint from FTHR-032.
- [ ] AC-7: This feather implements FTHR-028's `Endpointer` seam as given and does not modify
      `surface.py` or `stages.py`; any seam problem is raised against FTHR-028.
- [ ] AC-8: Molt evidence states that a green suite proves the endpointing **policy**, not that the
      timing values are well-tuned for real speech (which is FTHR-033 manual smoke / Pi tuning).
- [ ] AC-9: Only `hearth/audio/endpoint.py` and `tests/test_audio_endpoint.py` are added/changed
      (plus at most a single noted `pyproject.toml` dependency line), keeping wave 2 disjoint from
      FTHR-029/031/032; the `vad` extra's `setuptools<81` pin is undisturbed.
- [ ] AC-10: `ruff check .` is clean and the full existing test suite passes.
