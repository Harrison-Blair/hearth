---
id: FTHR-026
title: Concurrent veneer proof
plumage: PLM-007
status: fledged
priority: P0
depends_on: [FTHR-024]
authored: 2026-07-17T08:21:29Z
agent: fledge-orchestrate/planning
fledge_version: 0.6.7
---

# FTHR-026: Concurrent veneer proof

## Description

Proves the engine serves **multiple veneers at once** (FC-5), that their conversations are
**isolated** (FC-6), and that the engine **does not serialize turns across them** (FC-7). The
user's words: *"I will run multiple veneers at the same time on one device sometimes, that
should be handled properly as well."*

**This feather is unusual and it is worth being straight about why.** All three properties are
expected to hold already, by construction rather than by intent: the gateway assigns a fresh
`session_id` per connection (`server.py`), `Loop` holds only injected collaborators and is
therefore stateless per turn and reentrant (`loop.py:196-204`), and history is reconstructed
per-session from the log (`loop.py:283`). Nothing enforces any of that, and nothing would notice
if it broke — with one surface, none of it is observable. The audio plumages then build directly
on top of it.

So this feather **adds no production behavior**. Its whole substance is tests, and its value is
turning three accidental properties into guaranteed ones before two real surfaces depend on
them. If a test here fails, that is not a test to adjust — it is a genuine defect the
single-surface arrangement was hiding, and it should be raised as a finding (see Approach).

## Affected Modules

See `.fledge/nest/architecture.md` → *request path*; `.fledge/nest/modules.md` → *loop*, *veneer*.

- `tests/test_gateway_concurrency.py` (new) — **the only file this feather adds or changes.**

**`tests/conftest.py` is deliberately NOT touched.** The feather outline provisionally allotted
it, but on reading it (it holds LLM-backend fixtures, a logging-isolation autouse fixture, and
`HostRouter`) nothing there is needed here, and a fake veneer has exactly one consumer. Keep it
in the test module that uses it. This also removes the last file where this feather and FTHR-025
could have collided — with `conftest.py` untouched, the two share **no file at all**.

**Files this feather must NOT touch:** everything else. In particular `hearth/loop.py`,
`hearth/gateway/**`, `hearth/veneers/**`, and `tests/conftest.py` (FTHR-025 owns the first three
concurrently). If proving these properties appears to require a production change, stop — see
Approach.

## Approach

**The fake veneer.** Per the user's accepted answer, prove N>1 in tests with a fake rather than
shipping a second real surface — there is no second real surface until PLM-008, and production
code with no production caller is dead code. The fake is a test-local client: connect, submit a
turn, read messages. `tests/test_gateway.py`'s `_serve` helper (`:36-39`) and
`test_e2e_gateway.py`'s `_SlowFakeLoop` (`:439-450`) are the existing precedents — reuse their
shape rather than inventing a new one.

**Sequence is not concurrency, and this is the whole trap.** A test that opens a connection,
takes a turn, closes it, then opens a second and takes another turn would **pass while proving
nothing** — it demonstrates the engine can be used twice, which was never in doubt. The
connections must be open **simultaneously**, with turns **interleaved**.

**The strong shape for FC-7, and the one to build:** gate the fake `Loop` so that turn A cannot
complete until turn B has completed — e.g. A awaits an `asyncio.Event` that B's completion sets.
Under a correctly non-serializing engine, B runs while A is parked and both finish. **Under a
serializing engine this test cannot pass — it deadlocks and times out**, because B would be
queued behind the A that is waiting for it. That is the property worth having: a test that
*cannot* pass when the behavior breaks, rather than one that merely happens to pass when it
works. Give it a bounded timeout so the failure is a clean, legible timeout rather than a hung
suite.

**For FC-6 (isolation), assert on the right thing.** Do not assert only that the log has two
sessions — that is nearly tautological given a per-connection `session_id`. Assert that **turn
A's text never appears in the messages the backend receives for B's turn**. History is
reconstructed into the backend `messages` (`loop.py:283-293`), so the messages are where
leakage would actually show. A test that checks only session ids would pass even if history
bled across.

**If a test fails, it is a finding, not a fixture problem.** These properties are expected to
hold today. A failure means the single-surface arrangement was hiding a real defect — one the
audio plumages would inherit. Do not adjust the test to pass, and do not quietly fix production
code: this feather's file scope is one test module, and a production change here could collide
with FTHR-025 running concurrently. Stop and raise it.

## Tests

**The test-first cycle needs an honest adaptation here, and the repo's own rule prescribes it.**
These tests describe behavior that already exists, so they will pass on first run against
unchanged code. Step 2 as normally written — "observe them fail" — is therefore impossible, and
the wrong response is to wave the rule through: a test that has only ever been seen passing
proves nothing, which is exactly what the rule exists to prevent.

The user's standing rule already covers this case exactly: *"New test for a feature: temporarily
break or stub out the feature and confirm the test fails, then restore."* So the cycle here is:

1. Write the test; confirm it passes against unchanged code.
2. **Deliberately break the property it claims to prove** — for FC-7, wrap `run_turn` in a
   global lock so the engine serializes; for FC-6, force a constant `session_id` across
   connections instead of the per-connection one; for FC-5, that a second connection is served
   at all.
3. **Confirm the test fails** — and fails for the *right reason* (the serialization test should
   time out on the deadlock; the isolation test should show A's text in B's messages).
4. **Restore** the code, confirm the test passes again.
5. Record the break, the observed failure, and the restore as molt evidence, per property.

That sequence is what makes these tests real. Without it they are three tests that have only
ever been green, guarding nothing.

- `test_two_veneers_connected_concurrently_are_both_served` (new) — two connections open
  **simultaneously**, both take turns, both get answers, with neither closed before the other
  opens. *Break to verify:* refuse or stall the second connection. Satisfies FC-5 / PLM-007 AC-5.
- `test_concurrent_veneers_hold_isolated_conversations` (new) — with both connected, a turn on A
  does not enter B's conversation: assert **A's text is absent from the backend messages for B's
  turn**, not merely that session ids differ. *Break to verify:* share one `session_id` across
  connections; the test must then see A's text in B's messages. Satisfies FC-6 / PLM-007 AC-6.
- `test_engine_does_not_serialize_turns_across_veneers` (new) — **the load-bearing one.** Turn A
  is gated on turn B's completion; both complete within a bounded timeout. *Break to verify:*
  a global lock around `run_turn` — the test must then deadlock and time out. Satisfies FC-7 /
  PLM-007 AC-7.

**What a green suite would NOT catch here.** Ordinarily the risk is untested code. Here it is the
inverse: **these tests could be green and worthless.** Written as sequence rather than
concurrency, or asserting on session ids rather than message content, they would pass against an
engine that serializes every turn and bleeds history between surfaces — reporting the exact
opposite of the truth, with the plumage's concurrency claim stamped verified. That is a worse
outcome than having no test, because it would be believed. The break-and-restore evidence in
AC-2 is what distinguishes a real proof from a green rubber stamp, and it is the only thing that
can: nothing about a passing run tells you which of the two you have.

## Acceptance Criteria

- [x] AC-1: The three tests below pass against unchanged production code.
- [x] AC-2: **Each test was verified by breaking the property it proves** — serialize `run_turn`
      under a global lock; force a shared `session_id`; stall the second connection — the test
      was observed **failing for the right reason** in each case, and the code was restored. The
      break, the observed failure, and the restore are recorded as molt evidence **per test**.
      This replaces the usual observe-failing-first step, which is impossible for tests of
      existing behavior, and is the user's standing rule for this case. **Without this evidence
      the feather is not done**, regardless of a green suite.
- [x] AC-3: A test demonstrates two veneers connected **simultaneously** — both connections open
      at once, neither closed before the other opens — each served (satisfies PLM-007 FC-5,
      AC-5). Sequential connect/turn/close pairs do not satisfy this criterion.
- [x] AC-4: A test demonstrates a turn on one concurrently-connected veneer not appearing in
      another's conversation, asserted on **the messages the backend receives** rather than on
      session identifiers alone (satisfies PLM-007 FC-6, AC-6).
- [x] AC-5: A test demonstrates concurrent turns from two surfaces each being served with no
      engine-side serialization, structured so that a serializing engine **deadlocks and times
      out** rather than passing — turn A gated on turn B's completion, with a bounded timeout
      (satisfies PLM-007 FC-7, AC-7).
- [x] AC-6: The proof uses a test-local fake veneer; no production code is added, changed, or
      shipped for it — in particular no second real surface and no production concurrency
      machinery.
- [x] AC-7: `tests/test_gateway_concurrency.py` is the only file added or changed.
      `tests/conftest.py`, `hearth/loop.py`, `hearth/gateway/**`, and `hearth/veneers/**` are
      untouched, leaving FTHR-025 free to run concurrently.
- [x] AC-8: If any property failed, it was raised as a finding rather than fixed here or worked
      around by adjusting the test. (A failure means the single-surface arrangement was hiding a
      real defect that the audio plumages would inherit.)
- [x] AC-9: `ruff check .` is clean and the full existing test suite passes.
