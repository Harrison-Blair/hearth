---
id: FTHR-027
title: Documentation and vocabulary pass
plumage: PLM-007
status: egg
priority: P0
depends_on: [FTHR-025]
authored: 2026-07-17T08:24:05Z
agent: fledge-orchestrate/planning
fledge_version: 0.6.7
---

# FTHR-027: Documentation and vocabulary pass

## Description

Makes the project's documentation describe what the code now actually is: an engine with a
**gateway**, and **veneers** that are separate programs — starting with `chat` — each with its
own config file under `config/`. Satisfies FC-15.

**This is not a tidy-up, and it should not be treated as one.** Every stale line in this repo's
docs got there the same way: a plumage changed the code and left the prose describing the old
world. That pattern has already cost this project real money — during this plumage's own
planning, `CLAUDE.md`'s stale architecture description contributed to a full misread of what a
"veneer" is, and the resulting breakdown had to be re-gated from scratch. Docs that lie are not
cosmetic debt; they mislead the next reader, and the next reader is often an agent that will act
on them.

So this feather's bar is: **a reader landing on this repo cold gets the true story** about the
engine, the veneers, and how to run and configure each.

## Affected Modules

See `.fledge/nest/index.md`; `.fledge/nest/architecture.md`.

- `README.md` — the working/roadmap table (`:15` names the WebSocket "veneer" control surface),
  and any description of how you talk to hearth.
- `CLAUDE.md` — `:14` ("localhost WebSocket 'veneer' control surface"), `:56-57` (the
  `config.yaml` / `default-config.yaml` pair), `:68` (the secrets rule's reference to
  `config.yaml`), `:75` (the request path — `Veneer` (WebSocket server, `veneer/`) → …), `:98`
  (the `veneer/` seam), `:110` (the config section list, which names `veneer`).
- `MANUAL_SMOKE.md` — `:1` and `:4` (names the veneer and `tests/test_e2e_veneer.py`), `:33-35`
  (`python -m hearth.veneer.client` — **the instruction a user actually follows**), `:56`, and
  the client references at `:42`, `:72`, `:82`.
- `pyproject.toml:14` — the `websockets` comment ("veneer server/client"), explicitly left for
  this feather by FTHR-023.

**Do not touch `.fledge/`.** Fledged specs and molt evidence are historical records of what was
decided when — they are never rewritten, even when superseded.

## Approach

Work from the finished code, not from this feather's list — the list is what was true when this
was authored, and FTHR-022 through FTHR-025 will have moved things. `grep -rniI veneer` across
docs is the starting point; FTHR-023's molt evidence records the accounting of every remaining
hit and which feather owned it, so read that first.

**What must be true after this feather:**

1. **The vocabulary is settled.** "Veneer" means a user-facing program, never the engine's
   channel. The engine's channel is the gateway. No doc describes the superseded arrangement
   where a "veneer" is the WebSocket server.
2. **Running each component is documented and correct.** The engine is `hearth run`; the chat
   veneer is `hearth-chat`. `MANUAL_SMOKE.md:35`'s `python -m hearth.veneer.client` is the line
   that matters most here — it is a **procedure someone follows verbatim**, and after FTHR-024
   that module does not exist. A stale README paragraph misleads; a stale smoke step fails in
   the user's hands.
3. **The config layout is documented.** `config/engine.yaml` + `config/defaults/engine.yaml`,
   `config/chat.yaml` + `config/defaults/chat.yaml`, one shared loading facility, per-component
   files. `CLAUDE.md:56-57`'s two-file description is superseded. **`CLAUDE.md:68`'s secrets
   rule must survive the edit intact** — `.env` only, never the YAML, per FTHR-015. Update the
   filename it names; do not weaken the rule.
4. **The architecture description is true**, including that veneers are separate processes
   reaching the engine only over the wire, that multiple may run at once with isolated
   conversations, and that turns are logged with their originating surface.
5. **`CLAUDE.md:110`'s config-section list matches `Settings`.** It currently names `veneer`,
   which FTHR-024 deleted.
6. **`CLAUDE.md:81` and `:88` say Vesta, not Calcifer** — see the named exception below.

**One named exception: the orphaned persona lines.** `CLAUDE.md:81` and `:88` describe the
persona as **Calcifer**. The persona is **Vesta** — PLM-005 (fledged) settled it, and
`tests/test_config.py:149` asserts the prompt says `"You are Vesta."` and that `"calcifer"` does
not appear in it. So the file's architecture section contradicts both the code and a passing
test.

PLM-007's Out of Scope says the persona is settled elsewhere and untouched here, and ordinarily
that would end it. It does not, for one specific reason: **these two lines are orphaned.**
PLM-005 is fledged, fledged specs are never reopened, and no plumage claims them — so "leave it
for the owner" has no owner, and means "false forever". This feather is already rewriting that
exact section of that exact file. The user was asked and chose to correct them here.

**This is a narrow, named exception for two lines — not a licence to sweep stale docs.** Correct
`:81` and `:88` to Vesta and nothing else. Anything not listed in this feather's scope stays.

**Known-false lines this feather must LEAVE ALONE.** Found during interrogation and recorded
deliberately — false *today*, before and independently of this plumage, and **owned by PLM-008**,
which is why they are not the exception above:

- `CLAUDE.md:8-9` ("Wake word: **Calcifer**"), `:18` (`models/wake/calcifer.onnx`, a file that
  does not exist — only `vesta.onnx` does), `:124` (`manifest.py select` sets `wake.threshold`),
  and `README.md:22-24` (claims **both** wake models already exist; only Vesta is trained).
  **PLM-008 FC-14/AC-14 explicitly owns all of these** — it corrects which models are trained
  and kills the single-shared-threshold claim, against wake configuration that does not exist
  until PLM-008. Fixing them here would duplicate that work and force PLM-008 to be re-checked
  against already-edited lines.

Note the asymmetry, and preserve it: the persona lines are corrected because **nothing** will
ever correct them; the wake lines are left because **something specific will**. They are listed
so the implementer knows they were **seen and assigned**, not missed. If you believe one is
genuinely in this feather's scope, raise it — do not silently expand.

## Tests

**There are no unit tests for prose, and inventing one would be theatre.** This feather changes
documentation only; nothing in `pytest` asserts on `README.md`'s claims, and a test that grepped
for a word would pin the word, not the truth of the sentence around it. Saying so is more honest
than manufacturing a green check.

What *can* be mechanically verified, and must be:

- **`grep -rniI veneer` across all documentation**, with every remaining hit deliberate and
  correct under the settled vocabulary (i.e. referring to a user-facing program). This is the
  same accounting discipline FTHR-023 used for code, applied to docs. Record it as molt evidence.
- **Every command in `MANUAL_SMOKE.md` is executed as written**, and works. This is the one part
  of this feather that can genuinely break in a user's hands, and the only way to know a
  procedure is correct is to follow it. See AC-3.
- The existing suite must still pass — `pyproject.toml` is edited here (a comment only), and
  `CLAUDE.md`/`README.md` are read by no test.

## Acceptance Criteria

- [ ] AC-1: Documentation describes the engine, the `chat` veneer, how each is run
      (`hearth run`, `hearth-chat`) and configured (`config/engine.yaml`, `config/chat.yaml` via
      the shared facility), and the settled vocabulary where "veneer" means only a user-facing
      program; no documentation describes the superseded single-surface arrangement (satisfies
      PLM-007 FC-15, AC-14).
- [ ] AC-2: A `grep -rniI veneer` over all documentation is recorded as molt evidence, with every
      remaining hit deliberate and correct under the settled vocabulary. No hit describes the
      engine's channel as a veneer.
- [ ] AC-3: **Every command in `MANUAL_SMOKE.md` was executed as written and works** — in
      particular the step that starts the chat veneer, which named a module FTHR-024 deleted. The
      commands run and their output are recorded as molt evidence. A procedure that has not been
      followed is not known to be correct, and this document exists to be followed verbatim.
- [ ] AC-4: `CLAUDE.md`'s secrets rule survives intact — `.env` only, never the YAML (FTHR-015) —
      with only the config filename it references updated. The rule is not weakened, softened, or
      dropped in the rewrite.
- [ ] AC-5: `CLAUDE.md`'s config-section list matches `Settings` as it actually is after
      FTHR-024; it no longer names a `veneer` section.
- [ ] AC-6: The architecture description states that veneers are separate processes reaching the
      engine only over the wire, that multiple may run concurrently with isolated conversations,
      and that turns are logged with their originating surface.
- [ ] AC-7: `CLAUDE.md:81` and `:88` name the persona as **Vesta**, matching PLM-005 (fledged)
      and `tests/test_config.py:149`. This is a narrow, named exception, taken because the lines
      are orphaned — no plumage owns them — and it extends no further than those two lines.
- [ ] AC-8: The known-false **wake-word** lines listed in Approach (`CLAUDE.md:8-9`, `:18`,
      `:124`, `README.md:22-24`) are **untouched** and remain owned by PLM-008 FC-14/AC-14;
      nothing in this feather's diff addresses them. (They are left precisely because something
      specific *will* correct them — the asymmetry with AC-7 is deliberate, not an inconsistency
      to tidy.)
- [ ] AC-9: Nothing under `.fledge/` was modified — fledged specs and molt evidence are
      historical records.
- [ ] AC-10: `ruff check .` is clean and the full existing test suite passes.
