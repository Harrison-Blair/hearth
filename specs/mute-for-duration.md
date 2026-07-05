# Spec: "Turn off for {time}" — mute wake detection for a duration

Status: ready for implementation
Author: Harrison (via spec session, 2026-07-03)

## Context

The assistant currently has no way to be told "leave me alone for a while."
Users want to temporarily disable wake-word activation (e.g. during a meeting or
a nap) without stopping the daemon. The command is safety-sensitive — a
misheard duration could silence the assistant for hours — so the assistant must
repeat the parsed duration back and require an explicit spoken confirmation
before muting.

This feature also introduces the pipeline's first **multi-turn exchange**
(a follow-up reply captured without a new wake word). That mechanism should be
built as a small, general seam — later features (disambiguation, destructive
confirmations) will reuse it.

## Behavior

### Happy path (voice)

1. User: "<wake word> … turn off for 20 minutes"
2. Assistant: "I'll turn off for 20 minutes. Say confirm if that's right."
3. Pipeline immediately records the next utterance — **no wake word needed** —
   transcribes it, and hands it back to the skill.
4. If the reply contains the word "confirm" (case-insensitive substring):
   assistant says "Okay, turning off for 20 minutes." and wake detection is
   disabled until the deadline.
5. Any other reply, or silence/no speech captured: assistant says
   "Okay, cancelled." and nothing changes.

### While muted

- Wake events are ignored: the pipeline keeps draining mic frames but does not
  run wake detection (or discards its events) until `muted_until` passes.
- **Reminders still fire.** Mute disables wake activation only; the
  `ReminderScheduler` is untouched.
- Typed commands via the TUI control channel (`VoicePipeline.submit_text`)
  still work — this is the escape hatch. A typed "turn back on" /
  "unmute" / "wake up" clears the mute immediately.
- When the deadline passes, wake detection resumes silently (log line only,
  no spoken announcement).

### Typed path (TUI chat)

Typed commands skip the confirmation exchange: typing has no STT-mishearing
risk, which is the whole reason the confirmation exists. A typed
"turn off for 20 minutes" mutes immediately and replies
"Okay, turning off for 20 minutes."

### Edge cases

- Duration can't be parsed → "Sorry, I didn't catch how long to turn off for."
  (mirror the timer skill's failure wording). No confirmation round.
- "Turn off" with no duration at all → same failure reply. An indefinite mute
  is out of scope.
- A new "turn off for X" while already muted can't happen by voice (wake is
  off) but can happen typed: it replaces the existing deadline.
- Unmute (typed or voice) when not muted → "I wasn't turned off."
- Mute state is **in-memory only**. A daemon restart clears it; that's an
  accepted second escape hatch.

## Design

### 1. Follow-up reply mechanism (pipeline seam)

- `SkillResult` (`assistant/core/events.py`) gains
  `expects_reply: bool = False`.
- `Skill` (`assistant/skills/base.py`) gains
  `async def handle_reply(self, cmd: Command) -> SkillResult` with a default
  implementation returning a generic failure — only skills that set
  `expects_reply` need to override it.
- `VoicePipeline._handle` currently speaks the result and returns. Change the
  **voice turn** so that when `result.expects_reply` is true (and only on the
  voice path, which has the frame stream available):
  1. speak the prompt,
  2. record another utterance with the existing `VadRecorder` (empty prefix —
     no preroll needed, the user is responding to a prompt),
  3. transcribe it,
  4. call `skill.handle_reply(Command(transcript))` (empty transcript for
     silence) and speak that result.
  One round only: an `expects_reply` on the reply's result is ignored (log a
  warning). Everything happens inside the existing arbiter hold for the turn,
  so reminders can't interject mid-exchange.
- `submit_text` (typed path) has no audio stream; it never runs the reply
  round. Skills are told which path they're on — see intent handling below —
  so the mute skill simply doesn't ask for confirmation on typed input.
  Concretely: `submit_text` already exists as a separate entry point; thread a
  `spoken: bool` flag through `_handle` to the skill via the `Command`
  dataclass (add `spoken: bool = True` field) rather than adding a parallel
  handler.

### 2. Mute state

- New tiny class `MuteState` (suggested home: `assistant/core/mute.py`):
  `muted_until: float | None`, methods `mute_for(seconds, now)`, `unmute()`,
  `is_muted(now) -> bool` (auto-expires). Pure, no asyncio, trivially
  unit-testable.
- `VoicePipeline` takes a `MuteState` in `__init__`. In the wake loop, when
  `mute.is_muted(now)`: skip `self._detector.process(frame)` (keep appending
  preroll or clear it — clear it, matching the arbiter-busy branch) and
  `continue`. Log one line on the muted→unmuted transition.

### 3. Mute skill

- New `MuteSkill` (`assistant/skills/mute.py`):
  - `name = "mute"`, `intents = {"mute", "unmute"}`.
  - Constructed with the shared `MuteState` and a `now` callable (injectable
    for tests, same pattern as `ReminderSkill`).
  - `mute` intent: parse duration from the command text with the existing
    `parse_duration` (`assistant/nlu/timespec.py`) and phrase replies with the
    existing `humanize`. On spoken commands return the confirmation prompt
    with `expects_reply=True`, stashing the pending seconds on the skill
    instance; on typed commands (`cmd.spoken is False`) apply immediately.
  - `handle_reply`: if the reply text contains "confirm" (case-insensitive),
    apply the stashed mute; otherwise cancel. Always clear the stash.
  - `unmute` intent: clear the mute (see edge cases).

### 4. Wiring (`assistant/app.py` only)

- Construct one `MuteState`, pass it to both `VoicePipeline` and `MuteSkill`.
- `registry.register(MuteSkill(mute_state))`.
- Add keyphrases for the tier-one `KeyphraseRouter` (where the other skills'
  phrases are wired in `app.py`): e.g. "turn off" → `mute`,
  "turn back on" / "unmute" / "wake up" → `unmute`. The tier-two
  `ClassifierRouter` picks up the new intent labels from the registry's
  candidate set automatically; the `CommandEntryRouter` gets them for free via
  `registry.intents`.

No new config values are required. If the implementer finds a cap on maximum
mute duration desirable, that is a follow-up, not part of this spec.

## Files to change

- `assistant/core/events.py` — `SkillResult.expects_reply`, `Command.spoken`
- `assistant/skills/base.py` — default `handle_reply`
- `assistant/core/pipeline.py` — reply round on the voice path; mute gate in
  the wake loop; `submit_text` sets `spoken=False`
- `assistant/core/mute.py` — new `MuteState`
- `assistant/skills/mute.py` — new `MuteSkill`
- `assistant/app.py` — wiring (state, skill registration, keyphrases)
- Tests: `tests/test_mute_state.py`, `tests/test_mute_skill.py`, plus new
  cases in the existing pipeline tests (`tests/test_pipeline.py`)

## Acceptance criteria

Each is a test (pytest, `asyncio_mode = auto`, stub components — no native
deps, matching the existing suite's style):

1. Spoken "turn off for 20 minutes" → skill returns a prompt containing
   "20 minutes" with `expects_reply=True`; pipeline records a follow-up and
   passes it to `handle_reply`.
2. Reply "confirm" (also "yes, confirm it") → mute applied,
   `MuteState.is_muted` true, spoken acknowledgement.
3. Reply "no" / empty transcript (silence) → not muted, "cancelled" reply.
4. While muted, a frame that would trigger the wake detector does not start a
   turn; after the deadline (advance the injected clock) the same frame does.
5. Reminders fire while muted (scheduler path unaffected).
6. Typed "turn off for 10 minutes" mutes immediately, no confirmation round.
7. Typed "turn back on" while muted → unmuted; when not muted → "I wasn't
   turned off."
8. Unparseable duration → failure reply, `success=False`, no state change,
   no reply round.
9. A reply result with `expects_reply=True` does not trigger a second round.

## Out of scope

- Indefinite mute ("turn off until I say otherwise").
- Persisting mute across restarts.
- Muting reminder announcements.
- A spoken announcement when the mute expires.
- Generalizing the reply mechanism beyond one round.

## Verification

- `pytest` — full suite green, including the new tests above.
- `ruff check assistant tests` clean.
- Manual (with hardware or the TUI): boot `python -m tui`, type
  "turn off for 1 minute" in the chat box, observe the daemon log shows wake
  events ignored, and that wake works again after a minute. With a mic:
  speak the full confirm flow end-to-end.
