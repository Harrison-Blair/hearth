---
id: FTHR-024
title: Chat veneer as a standalone process
plumage: PLM-007
status: fledged
priority: P0
depends_on: [FTHR-022, FTHR-023]
authored: 2026-07-17T08:09:03Z
agent: fledge-orchestrate/planning
fledge_version: 0.6.7
---

# FTHR-024: Chat veneer as a standalone process

## Description

**The tracer completes here.** After this feather a user surface is a separately-runnable
program with its own name, its own config file, and no route to the engine but the wire — which
is PLM-007's entire claim, proven end to end before any audio exists.

It promotes today's `hearth/veneer/client.py` — a "trivial stdin/stdout text client" per its own
docstring — into `hearth/veneers/chat/`, a first-class veneer runnable as `hearth-chat`
(FC-3). Alongside it, `hearth/veneers/base.py` establishes the **client contract** every
surface implements: connect, submit a turn, parse inbound messages, fail fast when the engine is
unreachable (FC-13). Both audio plumages are implementations of that contract, so what this
feather defines, they inherit.

It also finishes what FTHR-022 and FTHR-023 deliberately left half-done. **This feather inherits
the dual-section cleanup obligation**: entering it, `config/engine.yaml` carries *both* a live
`veneer:` section and an unused `gateway:` section (FTHR-022 added the latter and removed
nothing, so it could run parallel to FTHR-023). This feather is what ends that temporary state —
it repoints the engine at `settings.gateway`, deletes `VeneerConfig` and the `veneer:` section
outright with no compatibility shim (FC-11, FC-12), and deletes the `hearth/veneer/` package,
which FTHR-023 left holding only the client. **If this feather lands and a `veneer:` section
still exists anywhere, the wave's transitional state has outlived its owner and the feather is
not done.** AC-6 exists to make that unmissable.

**The largest blast radius in this plumage.** It changes how the user launches the program they
use daily, and deletes the package it lives in today. There is no `merge` gate; the ACs are the
check.

## Affected Modules

See `.fledge/nest/modules.md` → *veneer*; `.fledge/nest/architecture.md` → *request path*.

- `hearth/veneers/__init__.py`, `hearth/veneers/base.py` (new — the client contract)
- `hearth/veneers/chat/__init__.py`, `hearth/veneers/chat/__main__.py` (from
  `hearth/veneer/client.py`, via `git mv`)
- `hearth/veneer/` — **deleted** (holds only `client.py` entering this feather)
- `config/chat.yaml`, `config/defaults/chat.yaml` (new)
- `hearth/config.py` — remove `VeneerConfig` and the `veneer` field; add chat's settings model
  (see Approach on where it lives)
- `config/engine.yaml`, `config/defaults/engine.yaml` — remove the `veneer:` section
- `hearth/app.py` — `:74-78` repoint to `settings.gateway.host/.port`
- `pyproject.toml` — `[project.scripts]` gains `hearth-chat`
- `tests/test_chat.py`, `tests/test_chat_contract.py` (new)
- `tests/test_veneer_client.py` → `tests/test_chat_client.py` (FTHR-023 left it in place)
- `tests/test_gateway.py`, `tests/test_e2e_gateway.py` — both import `send_turn` from the old
  client path; retarget to the contract's new home.
- `tests/test_config.py` — drop the `veneer:` fixture content and `settings.veneer` assertion.

**No concurrency constraint.** This feather runs alone in its wave; FTHR-022 and FTHR-023 are
merged before it starts. It may touch any file above.

## Approach

**1. `hearth/veneers/base.py` — the client contract.** Extract what any surface needs, from
what `client.py` already does:

- connect to an engine at a host/port,
- submit a turn and collect inbound messages until the terminal `done`/`error` (this is exactly
  today's `send_turn`, `client.py:15`),
- **fail fast on an unreachable engine** (FC-13) — new behavior, see below.

Keep it small and honest. `client.py` today imports stdlib, `websockets`, and one function-local
`from hearth.config import Settings` (`client.py:61`) — step 4 replaces that last engine
coupling with the chat-only settings model, and the resulting zero-`hearth`-imports property is
the process boundary made real. Establish it in `base.py`
and `chat/`: they may import the config facility, and nothing else from `hearth`. Specifically
no `hearth.brain`, `hearth.loop`, `hearth.memory`, `hearth.gateway`.

**Do not invent contract surface for the audio plumages.** Both are specified but unbuilt; a
base class shaped around imagined needs is speculative abstraction. Extract only what `chat`
demonstrably uses. Audio widens it when audio exists, with a real second caller to shape it.

**2. Fail-fast (FC-13).** Today `run_client` (`client.py:45`) lets `websockets.connect` raise —
a stack trace at an unreachable engine. Catch the connection failure and report plainly: name
the engine it tried to reach (host and port) and that the engine may not be running; exit
non-zero; **no traceback**. This lives in `base.py` — it is merged into this feather rather than
being its own, because a separate feather touching the same file would serialize for no benefit.
Note the divergence is deliberate and asymmetric: PLM-008 FC-10 gives the *audio* surface retry
with backoff, because it is unattended. Chat fails fast because you are at a terminal. Do not
build retry here or generalize toward it.

**3. `hearth/veneers/chat/`** — the promoted client. `git mv` the file so history follows.
Behavior must reproduce today's console exactly (AC-3, FC-3): the `> ` prompt, the red `[hearth]`
answer tag, `…label` tool activity, `error: …` errors, the non-blocking stdin read
(`client.py:39-42` — its docstring explains it keeps keepalive pongs flowing while idle; do not
"simplify" it away).

**4. Chat's config.** `config/chat.yaml` + `config/defaults/chat.yaml` with `engine: {host, port}`
— chat's view of where the engine is (the accepted Q1=A naming: the engine configures its
`gateway:`, a veneer configures which `engine:` to reach). Load via FTHR-022's shared facility
with the `chat` component (FC-10) — **this feather is the facility's second caller and the proof
FTHR-022's parameterization was real.** If it turns out chat cannot use the facility without
changing it, that is a finding worth raising, not routing around with a second loader.

`main()` (`client.py:60-64`) currently builds the engine's full `Settings()` — it drags the LLM
schema, persona, and storage into the chat process to read two integers. Replace with a chat
settings model reading only `config/chat.yaml`. Where that model lives is the implementer's
call, but chat must not import the engine's `Settings`; if that means the facility needs to sit
somewhere neutral, do that rather than compromise the boundary.

**5. Delete the old surface** (FC-12, no shim): `VeneerConfig` and `Settings.veneer` from
`hearth/config.py`; the `veneer:` section from both engine YAMLs; `app.py:74-78` → `settings.gateway`;
`rm -r hearth/veneer/`. `HEARTH_VENEER__*` env vars die with the section — that is intended.

**6. `pyproject.toml`** — `hearth-chat = "hearth.veneers.chat.__main__:main"` (or wherever `main`
lands) in `[project.scripts]`.

**7. Tighten FTHR-023's completeness test.** It left `test_no_engine_side_component_named_veneer`
scoped to tolerate `hearth/veneer/client.py`. That tolerance expires here: after this feather,
nothing under `hearth/` is named veneer except `hearth/veneers/`. Tighten it — FTHR-023's body
flags this handoff.

## Tests

Test-first: (1) write them; (2) run against unchanged code, confirm each FAILS for the expected
reason; (3) implement until they pass.

- `test_chat_reaches_engine_only_over_the_wire` (new, `tests/test_chat_contract.py`) — asserts
  the `hearth.veneers` tree imports nothing from `hearth.brain`, `hearth.loop`, `hearth.memory`,
  or `hearth.gateway`. **This is FC-1's evidence and the contract both audio plumages inherit** —
  write it over the `hearth.veneers` package, not over `chat` specifically, so a future surface
  is covered the day it is added. *Fails before:* the package does not exist.
- `test_chat_fails_fast_on_unreachable_engine` (new, `tests/test_chat.py`) — pointed at a closed
  port, chat prints a message naming the host and port it tried and that the engine may not be
  running, exits non-zero, and prints **no traceback**. Assert on all three; the no-traceback
  part is the half that would otherwise regress unnoticed. *Fails before:* `websockets.connect`
  raises unhandled. Satisfies FC-13.
- `test_chat_loads_only_its_own_config` (new, `tests/test_chat.py`) — chat loads `config/chat.yaml`
  and reads `engine.host`/`engine.port`; assert it does **not** require the engine's config to be
  present at all — that is the real content of FC-9's "independently of the other's". *Fails
  before:* `main()` builds the engine's `Settings()`.
- `test_no_component_named_veneer` (existing, tightened from FTHR-023) — nothing under `hearth/`
  named veneer except `hearth/veneers/`. *Fails before:* `hearth/veneer/client.py` exists.
- `test_engine_binds_via_gateway_config` (new, `tests/test_app.py`) — `_run_daemon` serves on
  `settings.gateway.host/.port`. *Fails before:* `app.py` reads `settings.veneer`.
- `test_veneer_config_section_is_gone` (new, `tests/test_config.py`) — `Settings` has no `veneer`
  attribute and `HEARTH_VENEER__PORT` does not influence anything. Pins FC-12's no-shim
  requirement. *Fails before:* the field exists.
- `tests/test_chat_client.py` (renamed from `test_veneer_client.py`), `test_gateway.py`,
  `test_e2e_gateway.py` — retarget `send_turn` imports. The e2e test drives the real stack
  through the client; it staying green is the strongest evidence the promotion preserved
  behavior.

**What a green suite would NOT catch here — and the AC that covers it.** Every test above runs
in-process against imported modules. **Nothing proves the thing the user actually does works.**
`[project.scripts]` entry points only exist after a reinstall, so `hearth-chat` can be entirely
broken — bad module path, `main` not where the entry point says — with `pytest` fully green. The
same suite cannot see the interactive console: the prompt, the colored tag, stdin behavior at a
real terminal. And this feather **deletes the user's daily driver's package**, so a mistake here
is the user's next `hearth` session failing, not a red CI run.

So **AC-4 requires it actually run**: `pip install -e .`, start the engine, run `hearth-chat` as
the console script, take a real turn, see the answer; and run it again with the engine stopped
to see the fail-fast message and non-zero exit. Record the commands and their output as molt
evidence. A passing suite does not satisfy AC-4. Add this to `MANUAL_SMOKE.md` if it has a
natural home there.

## Acceptance Criteria

- [x] AC-1: The tests listed above were observed failing before implementation and pass after.
- [x] AC-2: A veneer is a separate process reaching the engine only over the wire: a test asserts
      the `hearth.veneers` tree imports nothing from `hearth.brain`, `hearth.loop`,
      `hearth.memory`, or `hearth.gateway`, and the test is written over the package so any
      future surface is covered (satisfies PLM-007 FC-1, and AC-4's "applies to any surface").
- [x] AC-3: `chat` reproduces today's console behavior — `> ` prompt, turn submission, `…label`
      tool activity, red `[hearth]` answer tag, `error: …` display, non-blocking stdin read.
- [x] AC-4: `hearth-chat` is verified as an **installed console script** against a **running
      engine**: a real turn answered, and — with the engine stopped — a plain message naming the
      engine's host/port, a non-zero exit, and no traceback. Commands and output recorded as molt
      evidence (satisfies PLM-007 FC-3, FC-13). **A passing test suite does not satisfy this
      criterion**; nothing in the suite exercises the entry point or the terminal.
- [x] AC-5: Chat reads only `config/chat.yaml`, via FTHR-022's shared facility, as its second
      caller; a test asserts chat loads with the engine's config absent (satisfies PLM-007 FC-9,
      FC-10). Chat does not import the engine's `Settings`.
- [x] AC-6: **The dual-section transitional state is ended.** `VeneerConfig`, `Settings.veneer`,
      and the `veneer:` section in both engine YAMLs are gone with no compatibility alias; the
      engine binds via `settings.gateway`; `hearth/veneer/` is deleted; a test asserts no
      `veneer` attribute on `Settings` and that `HEARTH_VENEER__*` influences nothing (satisfies
      PLM-007 FC-11, FC-12).
- [x] AC-7: Nothing under `hearth/` is named veneer except `hearth/veneers/`; FTHR-023's
      completeness test is tightened accordingly.
- [x] AC-8: `base.py` contains only contract surface `chat` demonstrably uses — no speculative
      hooks for the unbuilt audio surfaces, and no retry (PLM-008 FC-10 owns retry, deliberately
      asymmetric).
- [x] AC-9: The `hearth/veneers` tree imports only stdlib, `websockets`, and the config facility,
      preserving the property today's `client.py` already has.
- [x] AC-10: `ruff check .` is clean and the full existing test suite passes.
