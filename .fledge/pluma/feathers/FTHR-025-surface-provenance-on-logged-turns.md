---
id: FTHR-025
title: Surface provenance on logged turns
plumage: PLM-007
status: fledged
priority: P0
depends_on: [FTHR-024]
authored: 2026-07-17T08:18:24Z
agent: fledge-orchestrate/planning
fledge_version: 0.6.7
---

# FTHR-025: Surface provenance on logged turns

## Description

Makes every logged turn attributable to the surface it came from (FC-8), so a spoken turn can be
told from a typed one after the fact.

Today `Loop.run_turn` logs `user_input` with the provenance `"user"` (`loop.py:273`) — a constant.
With one surface that is invisible; with two, **every turn in the log looks identical** and the
distinction the user asked for does not exist. The surface declares its own identity when it
submits a turn, it rides the wire on the request, and the engine writes it into the log's
existing `provenance` column.

**The architectural line this feather must not cross.** It touches `hearth/loop.py` — the
engine's core — and the whole plumage exists to prove the engine and the surfaces are separate.
An **opaque provenance string is not a dependency**: no import, no branch, no behavior keyed on
it. The engine must never care *which* surface a turn came from — only record it. The moment
anything in the engine reads the value to decide something, the engine knows about surfaces, and
this plumage's central claim is compromised **by its own provenance feature**. AC-4 makes that a
criterion rather than a hope, because a green suite would not catch it.

## Affected Modules

See `.fledge/nest/modules.md` → *loop*, *memory*, *veneer*; `.fledge/nest/domain.md` → *event log*.

- `hearth/gateway/protocol.py` — `Request` (`:19-22`) gains `surface`; `parse_request` (`:25`)
  reads it.
- `hearth/gateway/server.py` — `:82-84` passes it into `run_turn`.
- `hearth/loop.py` — `run_turn` (`:266`) gains `surface`; `:273`'s `"user"` constant becomes it.
- `hearth/veneers/base.py` — the contract sends the surface with each turn.
- `hearth/veneers/chat/` — declares itself as `chat`.
- `tests/test_gateway.py`, `tests/test_gateway_errors.py`, `tests/test_loop.py`,
  `tests/test_e2e_gateway.py`, `tests/test_chat.py` — call sites and assertions.

**Files this feather must NOT touch** (FTHR-026 owns them, concurrently):
`tests/test_gateway_concurrency.py`, `tests/conftest.py`. If you need a fixture, put it in the
test module that uses it — do not reach into `conftest.py`, or the two feathers collide in one
file.

`hearth/memory/log.py` needs **no change**: the `provenance` column already exists
(`log.py:47`) and `append()` already takes it (`log.py:59`). Do not alter `EventLog` — it is
append-only by design (no update/delete), and this feather has no reason to touch it.

## Approach

**1. `Request` gains `surface`** and `parse_request` reads it. A frame lacking it raises
`KeyError` and hits the **existing** malformed-frame path (`server.py:65-76`), which rejects it
on the wire without echoing its content and keeps the connection alive. That is the behavior you
want and it is already built — do not add a second rejection path, and do not give `surface` a
default on the wire, which would silently re-create today's indistinguishable turns.

**2. `run_turn` gains `surface` — with no default value.** This matters more than it looks.
A defaulted parameter (`surface: str = "user"`) would let the gateway forget to pass it while
every test stays green and every turn silently logs the old constant — the feature present in
the signature and absent in the log. **Make it required**, so every call site must state the
surface and the ones that don't fail loudly.

**3. `:273`'s constant becomes the surface value.** Nothing reads `provenance == "user"` — the
history reconstruction at `:278-283` filters on `event.type`, not provenance — so replacing the
constant breaks no reader. Verify that before relying on it rather than trusting this note.
The other provenance values in the engine (`"loop"` for turn errors, and the gateway's own for
malformed frames) are the **engine** speaking about itself, not a surface; leave them alone.

**4. The contract sends it.** `base.py` includes the surface in the turn it submits; `chat`
declares `"chat"`. Put the surface's identity where a surface declares it once — an audio
veneer must be able to say `"audio"` without touching the engine or the base's logic. That is
FC-8's point: the set of surfaces is data, not structure.

**Constraint — the engine does not branch on it.** The engine may *pass* and *store* the value.
It may not compare it, switch on it, validate it against a known list, or key any behavior on
it. There is no enum of surfaces in the engine, and there must not be: an enum would mean adding
a surface requires an engine change, which is the coupling this plumage removes.

**On trusting the value.** It is client-declared and lands in an append-only log. That is
acceptable and deliberate: it is a localhost channel already accepting arbitrary transcript text,
so an arbitrary surface string is no wider a door. Do **not** add an allowlist to "harden" it —
that is precisely the engine-side knowledge of surfaces this feather forbids. If the value's
shape genuinely needs bounding, raise it as a finding rather than deciding it here.

## Tests

Test-first: (1) write them; (2) run against unchanged code, confirm each FAILS for the expected
reason; (3) implement until they pass.

- `test_turn_logged_with_originating_surface` (new, `tests/test_gateway.py`) — a turn submitted
  declaring a surface is logged with that surface as the `user_input` provenance. *Fails
  before:* the provenance is the `"user"` constant. Satisfies FC-8.
- `test_turns_from_different_surfaces_are_distinguishable` (new, `tests/test_gateway.py`) — two
  turns declaring different surfaces are distinguishable in the log. This is PLM-007 AC-8's
  literal requirement and the reason the feature exists. *Fails before:* both log `"user"`.
- `test_engine_does_not_branch_on_surface_value` (new, `tests/test_loop.py`) — **AC-4's
  evidence, and the most important test in this feather.** Run the same turn through `run_turn`
  under several unrelated, arbitrary surface strings — including values no real surface would
  ever send — and assert the outcome is **identical in every respect except the recorded
  provenance**: same answer, same messages sent to the backend, same events emitted, same log
  events but for that one field. Parameterize it over the arbitrary values so it holds for the
  **general case** rather than for `chat` and `audio` specifically; a future surface is then
  covered the day it is added, with no one remembering to extend this. *Fails before:*
  `run_turn` takes no `surface`.
- `test_run_turn_requires_surface` (new, `tests/test_loop.py`) — calling `run_turn` without a
  surface is an error, not a default. Pins step 2 above. *Fails before:* the parameter does not
  exist.
- `test_frame_without_surface_is_rejected_as_malformed` (new, `tests/test_gateway_errors.py`) —
  a frame omitting `surface` takes the existing malformed-frame path: rejected on the wire, its
  content never echoed, connection alive. *Fails before:* `parse_request` ignores the field.
- Existing call sites in `test_loop.py`, `test_e2e_gateway.py`, `test_gateway_errors.py` —
  updated to pass a surface. They fail first with a missing-argument error, which is step 2
  working as intended.

**What a green suite would NOT catch — and the AC that covers it.** A suite proves the value is
*stored*. It cannot prove the engine is *indifferent* to it. An implementer could thread the
surface through correctly, pass every test above, and — here or in a later feather — add a
single `if surface == "audio":` in the engine. Every test stays green; the log still records
the surface; **and the architectural claim this whole plumage exists to prove is dead**, because
the engine now knows what a surface is. `test_engine_does_not_branch_on_surface_value` is the
guard, which is why it is parameterized over arbitrary values rather than the two real ones: a
branch on any specific surface name makes it fail. Back it with a read of the diff — the engine
must contain no comparison against a surface value — and record that as molt evidence.

## Acceptance Criteria

- [x] AC-1: The tests listed above were observed failing before implementation and pass after.
- [x] AC-2: Each logged turn records its originating surface as the `user_input` provenance, and
      a test asserts turns from different surfaces are distinguishable in the log (satisfies
      PLM-007 FC-8, AC-8).
- [x] AC-3: `run_turn` takes the surface as a **required** parameter with no default, so a call
      site that omits it fails loudly rather than silently logging the old constant; a test pins
      this.
- [x] AC-4: **The engine does not branch on the surface value.** It passes and stores it and
      does nothing else with it: no comparison, no switch, no validation against a known list, no
      enum of surfaces anywhere in the engine. A test parameterized over arbitrary surface
      strings asserts identical behavior — same answer, same backend messages, same emitted
      events, same log events but for the provenance field — and the diff is confirmed to contain
      no comparison against a surface value, recorded as molt evidence. **A green suite alone
      does not satisfy this criterion.** (Guards PLM-007 FC-1: an opaque string is not a
      dependency; a branch is.)
- [x] AC-5: A surface declares its own identity in one place, so a new surface can name itself
      without any engine or contract change; `chat` declares `chat`.
- [x] AC-6: A frame omitting the surface is rejected via the **existing** malformed-frame path —
      not echoed, connection alive — with no second rejection path added and no wire-level
      default.
- [x] AC-7: `hearth/memory/log.py` is unchanged: the existing `provenance` column and `append()`
      signature carry this feature, and `EventLog` remains append-only.
- [x] AC-8: The engine's own provenance values (`"loop"` for turn errors, the gateway's for
      malformed frames) are unchanged — those are the engine speaking about itself, not a
      surface.
- [x] AC-9: `tests/test_gateway_concurrency.py` and `tests/conftest.py` are untouched by this
      feather, leaving FTHR-026 free to run concurrently.
- [x] AC-10: `ruff check .` is clean and the full existing test suite passes.
