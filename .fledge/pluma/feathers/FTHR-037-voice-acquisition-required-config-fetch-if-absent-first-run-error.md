---
id: FTHR-037
title: "Voice acquisition: required config, fetch-if-absent, first-run error"
plumage: PLM-009
status: egg
priority: P1
depends_on: [FTHR-035]
authored: 2026-07-17T16:09:56Z
agent: fledge-orchestrate/planning
fledge_version: 0.6.8
---

# FTHR-037: Voice acquisition: required config, fetch-if-absent, first-run error

## Description

Owns the **first-run voice experience** — the load-bearing UX of the whole speaking plumage. The
user's decision (PLM-009 Q3) is that a voice is **required and no default ships**, and no voice
exists in the repo at all. So the very first thing a user meets, if they have not named a voice, is
this feather's error; and once they have named one, this feather **fetches it if it is absent** so
naming costs one config line and a first run, not a setup ritual.

Three behaviours, all on disjoint files from the renderer (FTHR-036) and the player (FTHR-038):

1. **Absent-voice first-run error (FC-3) — the crux.** When no voice is configured, the surface
   refuses to start and reports a **clear, actionable message that names the missing setting and
   states how to discover valid voices**, exiting as a *configuration problem* (non-zero, **no
   stack trace**). It must read as an instruction — "set this, here's where voices come from" — not
   as a crash. This is the FTHR-032 lesson applied to UX: the `StopIteration`-style bare failure is
   exactly what this must not be; replace the would-be crash with a legible instruction.

2. **Fetch-if-absent on startup (FC-4).** When a voice *is* named but not present locally, fetch it
   **before serving begins**; an already-present voice is **not re-fetched**. A first run is
   therefore the install step — no separate procedure.

3. **Locate the voice for the renderer.** Resolve the configured voice name to the on-disk artifact
   FTHR-036's `Renderer` loads, so "named → present → rendered" is one unbroken path.

**The hard boundary the user drew (guard it).** The good error message is in scope; a
**`--list-voices` subcommand or any voice-audition/picker is explicitly out** (PLM-009 Out of
Scope, and your standing reminder). "How to discover valid voices" is a **pointer in the message**
(where voices come from / how to name one) — not a new command that browses or previews them. If a
brooder feels the message is insufficient without a lister, that is a finding to raise, **not** a
licence to grow the CLI. Keep this a message, not a feature.

**Boundaries.** This feather **consumes FTHR-035's `voice` config key** (unset ⇒ absent) and turns
that absence into the first-run error; it does **not** redefine the key. It does **not** render
(FTHR-036), touch a device or play anything (FTHR-038), or do barge-in. It fetches/locates a voice
and produces the absent-voice error — nothing more.

**Runs in wave 2, parallel with FTHR-036 (render) and FTHR-038 (playback+barge-in)** — three
disjoint workers against FTHR-035's seams/config. Depends on **FTHR-035** (the `voice` key and the
surface startup this hooks into).

## Affected Modules

See `.fledge/nest/index.md`; FTHR-035's `voice` config key and the audio surface's startup path
(where "check voice present, else fetch, else error" belongs — before serving); `training/manifest.py`
as a **style reference** for the clear-error / `SystemExit` idiom the module already uses (do not
import it — it is the wake registry, not voices); `hearth/config.py` (the shared facility loading
`voice`).

- `hearth/audio/**` — the startup voice check: resolve the configured voice, fetch-if-absent,
  or emit the absent-voice error and exit as a config problem. Hooks the surface's startup FTHR-035
  established; does not restructure it.
- `tests/` — new test module for the absent-voice error, fetch-if-absent, and no-re-fetch.

**Files this feather must NOT touch:** the `Renderer` (FTHR-036 — this feather does not synthesise),
the `Player`/device (FTHR-038), the `voice` **key definition** (FTHR-035 owns it), and the listening
input path. Do **not** add a CLI subcommand — no `--list-voices`, no picker. The engine is not
modified.

## Approach

**1. Startup order: check → fetch → serve, or error → exit.** At surface startup, read the
configured voice. If **unset**: emit the first-run error and exit non-zero as a config problem. If
**set but absent locally**: fetch it, then continue to serving. If **set and present**: continue,
no fetch. This ordering is the whole feature; make it observable so tests can assert each branch.

**2. The absent-voice message is a first-class artifact, not an afterthought.** It must (a) name
the exact config setting (FTHR-035's `voice` key, by its real name/path in `config/audio.yaml`);
(b) state **how to discover valid voices** as a pointer (where voices come from / the naming form),
**not** a command to run; (c) exit **without a traceback**, mirroring the `error:`/`SystemExit`
idiom `manifest.py` already uses. Assert the message *content* in a test — the setting name and the
discovery pointer must both be present — so a vague "voice not found" cannot pass.

**3. Fetch-if-absent, behind a seam.** The fetch (download/resolve) must be **injectable** so CI
proves the *policy* — fetch when absent, skip when present — with **no network**. A fake fetcher
records whether it was called; the test asserts it fires on absent and does **not** fire on present.
This is the same hermetic-seam discipline as the renderer/player doubles.

**4. Do not grow the surface's CLI.** The message points; it does not add a subcommand. Guard this
with a test asserting no new command/flag for listing voices exists — the user drew this line
explicitly (Q3 / Out of Scope), and it is easy to "helpfully" cross.

**Constraints.** Consume FTHR-035's key; do not render or play; no `--list-voices`; fetch behind an
injectable seam so CI is offline. Match existing style; surgical.

## Tests

Test-first: (1) write; (2) run against the unchanged surface (no voice check exists — it starts
without one), confirm FAIL for the expected reason; (3) implement until green.

- `test_absent_voice_refuses_to_start_with_actionable_message` (new) — with no voice configured,
  startup exits **non-zero with no stack trace**, and the message **names the config setting and
  states how to discover voices**. Assert both fragments are present. *Fails before:* the surface
  starts (or crashes) with no voice; no such message exists. FC-2, FC-3 — the crux.
- `test_configured_absent_voice_is_fetched_before_serving` (new) — a named-but-absent voice triggers
  the injected fetcher **before** serving begins. *Fails before:* no fetch-if-absent logic. FC-4.
- `test_present_voice_is_not_refetched` (new) — a named-and-present voice does **not** invoke the
  fetcher. *Fails before:* n/a until wired; pins the "no re-fetch" half so a naive always-fetch
  fails. FC-4.
- `test_fetch_is_hermetic_and_injectable` (new) — the fetch path is driven by an injected fetcher;
  CI performs **no network access**. Guards the offline property. *Fails before:* n/a until wired; a
  guard against a real download creeping in.
- `test_no_voice_listing_subcommand_is_added` (new) — no `--list-voices`/voice-picker command or
  flag is introduced; discovery is a pointer in the message only. *Fails before:* n/a; guards the
  user's explicit scope line so a later "helpful" addition is caught.

**What a green suite proves here.** Green proves the **startup policy and the message content** —
absent ⇒ actionable error + exit, absent-but-named ⇒ fetch, present ⇒ no fetch — all offline. It
does **not** prove a real voice actually downloads from a real source (that is a real-network fetch,
exercised when a human runs the first-run step and confirmed in **FTHR-039's smoke** as part of the
end-to-end audible run). The message's *wording quality* is human-judged; the test pins that the
setting name and discovery pointer are present, not that the prose is graceful. Molt evidence should
record both: the green policy proof and that the real-download + message-reads-well confirmation
lands at the first real run / FTHR-039.

## Acceptance Criteria

- [ ] AC-1: The tests listed above were observed failing before implementation and pass after.
- [ ] AC-2: With **no voice configured**, the surface **refuses to start**, emitting a clear message
      that **names the missing setting** and **states how to discover valid voices**, and exits
      **non-zero without a stack trace** — a configuration problem, not a crash; a test asserts both
      message fragments (satisfies PLM-009 FC-2, FC-3).
- [ ] AC-3: A **named-but-absent** voice is **fetched before serving begins**, and an
      **already-present** voice is **not re-fetched**; both branches proven with an injected fetcher
      and **no network** in CI (satisfies PLM-009 FC-4).
- [ ] AC-4: The fetch runs behind an **injectable seam** so CI is fully offline; a test guards the
      hermetic property (satisfies PLM-009 FC-11 for the acquisition path).
- [ ] AC-5: **No `--list-voices` / voice-audition / picker subcommand or flag is added** — discovery
      is a pointer inside the error message only; a test guards this explicit scope line (satisfies
      PLM-009 Out of Scope).
- [ ] AC-6: This feather **consumes FTHR-035's `voice` key** (unset ⇒ absent) and does not redefine
      it; it does **not** render (FTHR-036), play or touch a device (FTHR-038), or do barge-in — any
      config-key insufficiency was raised as a finding against FTHR-035.
- [ ] AC-7: Molt evidence records that CI proves the **startup policy and message content offline**;
      the **real download** and **whether the message reads well** are confirmed at the first real
      run / FTHR-039, not here.
- [ ] AC-8: `ruff check .` is clean and the full existing test suite passes.
