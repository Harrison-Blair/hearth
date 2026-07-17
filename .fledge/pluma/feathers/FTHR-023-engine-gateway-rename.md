---
id: FTHR-023
title: Engine gateway rename
plumage: PLM-007
status: pipping
priority: P0
depends_on: []
authored: 2026-07-17T08:05:57Z
agent: fledge-orchestrate/planning
fledge_version: 0.6.7
---

# FTHR-023: Engine gateway rename

## Description

Renames the engine-side WebSocket channel from "veneer" to "gateway", settling PLM-007's
vocabulary (FC-2) and freeing the word *veneer* to mean only the user-facing program.

`hearth/veneer/{server,protocol}.py` move to `hearth/gateway/`, and the class `Veneer` becomes
`Gateway`. This is the ambiguity PLM-007's Context calls out as "not cosmetic": today
`hearth/veneer/server.py` is the **engine's** listener while `hearth/veneer/client.py` is the
**user's** program, and the shared name actively misleads a reader about which side of the
boundary a component sits on. Both audio plumages inherit this vocabulary, so it is settled
before anything is built on it.

**Behavior is identical.** No logic changes: same wire format, same safety whitelist, same
per-connection session handling, same `ping_interval=None`. If the diff contains a behavior
change, the diff is wrong.

**Deliberately narrow.** This feather does **not**:

- touch `hearth/veneer/client.py` — it stays put, importing nothing that moves here. FTHR-024
  promotes it to `hearth/veneers/chat/`. So `hearth/veneer/` still exists after this feather,
  containing only the client; FTHR-024 deletes the package.
- touch `hearth/config.py` or the `veneer:` config section — FTHR-022 is editing that file in
  the same wave, and the section rename is FTHR-024's (FC-11/FC-12). `Gateway.serve()`
  therefore still reads `self._config.veneer.host/.port`. **That mismatch is expected and
  correct at this feather's boundary** — a `Gateway` reading a `veneer:` section looks wrong,
  and would be, if it were the end state. It is not; FTHR-024 finishes it.

## Affected Modules

See `.fledge/nest/modules.md` → *veneer*; `.fledge/nest/architecture.md` → *request path*.

- `hearth/gateway/server.py` (from `hearth/veneer/server.py`, via `git mv`)
- `hearth/gateway/protocol.py` (from `hearth/veneer/protocol.py`, via `git mv`)
- `hearth/gateway/__init__.py`
- `hearth/app.py` — `:39` import, `:71` construction, `:73-75` log line, `:78` serve call.
- `tests/test_veneer.py` → `tests/test_gateway.py`
- `tests/test_veneer_errors.py` → `tests/test_gateway_errors.py`
- `tests/test_e2e_veneer.py` → `tests/test_e2e_gateway.py`
- `tests/test_veneer_client.py` — **stays put** (see Approach — it covers both sides)
- `tests/test_app.py` — `:52`, `:75` monkeypatch targets; `:84` log assertion.
- `hearth/logging_setup.py:52` and `tests/test_console_formatter.py:111` — comments naming
  `hearth/veneer/server.py` by path (see Approach).

**Files this feather must NOT touch** (FTHR-022 owns them, concurrently): `hearth/config.py`,
`config/**`, `packaging/build.sh`, `tests/test_config.py`. Note `tests/test_config.py:36` and
`:67` reference the `veneer:` config section — leave them; that section is not renamed here.

## Approach

**1. `git mv` both modules** into `hearth/gateway/`, add `__init__.py`, update the intra-package
import (`server.py:16` imports from `hearth.veneer.protocol` → `hearth.gateway.protocol`).
Use `git mv` so history follows.

**2. Rename the class** `Veneer` → `Gateway` and update its docstring (`server.py:1`), which
currently opens "Veneer: localhost WebSocket server…". Update the in-body comment at
`server.py:37` ("the veneer is a long-lived localhost control channel") — it describes the
gateway, not a veneer.

**3. Update `hearth/app.py`.** The local variable, the import, and the log message at `:73`
("veneer serving host=%s port=%s" → "gateway serving …"). Leave `settings.veneer.host/.port` at
`:74-78` **as-is** — the config section is FTHR-024's.

**4. Rename the three test modules** with `git mv` and update their imports and docstrings.
`tests/test_app.py:84` asserts on the literal `"veneer serving"` log text — it must move to
`"gateway serving"` in step with the log line, and it is the test that fails if you change one
and not the other.

**`tests/test_veneer_client.py` is the awkward one** — it covers the client *and* the server's
keepalive, and imports both (`:14`). Do not rename or split it here: splitting it would put this
feather in `client.py`'s territory, which FTHR-024 owns. Update only its `server` import and its
`Veneer`→`Gateway` usage (`:68`). FTHR-024 renames and splits it when it moves the client.

**5. Fix the comments this rename makes stale.** `hearth/logging_setup.py:52` and
`tests/test_console_formatter.py:111` both name `hearth/veneer/server.py` by path; after this
feather that file does not exist. Fix them here — the feather that breaks a reference fixes it,
rather than leaving a known-wrong path pointing at nothing until the docs feather.
(`pyproject.toml:14`'s "veneer server/client" comment is **not** fixed here: it stays partly
true until FTHR-024 moves the client, and FTHR-026 owns it.)

**Constraint: a rename, not a refactor.** Do not restructure, do not "improve" the code you are
moving, do not touch the safety whitelist. Match existing style. Anything beyond the rename is
scope creep — raise it, don't do it.

## Tests

Test-first applies here in the form the change permits, and it is worth being precise about why
this feather is different: **a pure rename has no new behavior to pin**, and the honest thing is
to say so rather than invent a ceremonial test that proves nothing.

The existing suite *is* the test, and it is a strong one — `test_gateway.py`,
`test_gateway_errors.py`, `test_e2e_gateway.py`, and `test_veneer_client.py` already cover the
roundtrip, error surfacing, the whitelist, and the keepalive. If behavior changed, they fail.
So rather than fabricate a "test the rename happened" test, prove the rename is *complete*:

- `test_no_engine_side_component_named_veneer` (new, `tests/test_gateway.py`) — asserts no
  engine-side module is named "veneer": `hearth/veneer/server.py` and
  `hearth/veneer/protocol.py` no longer exist, and `hearth.gateway` provides them. This is
  AC-2's evidence and the one thing here that genuinely fails first — it fails today because
  those modules exist. Scope it so it does not trip on `hearth/veneer/client.py`, which
  legitimately still exists until FTHR-024. **Note for FTHR-024:** tighten this test when the
  client moves — at that point nothing under `hearth/` should be named veneer except
  `hearth/veneers/`.
- `test_app.py:84`'s `"gateway serving"` assertion (existing, retargeted) — fails first against
  the unchanged log line.

**The order still holds:** write/retarget those two, observe them FAIL for the expected reason,
then rename until they pass, with the rest of the suite green throughout.

**What a green suite proves here, and what it does not.** It proves the engine-side rename is
behavior-preserving. It does **not** prove there is no stale `veneer` reference left in a
string, comment, or docstring — nothing asserts on those. So run a final `grep -rniI veneer`
over the repo and account for **every** remaining hit as one of: (a) `hearth/veneer/client.py`
and its test, (b) the `veneer:` config section and its test, (c) `pyproject.toml:14`,
(d) user-facing docs — each owned by a named later feather — or (e) the malformed-frame
provenance string literal (`server.py:73` today), a logged **value** that AC-4 and FTHR-025
both require kept as-is. Any hit outside those five categories is this feather's to fix
(stale comments like `hearth/events.py:1,4` are comment edits, safe under AC-4). Record the grep and its accounting as molt evidence.

## Acceptance Criteria

- [x] AC-1: The tests listed above were observed failing before implementation and pass after.
- [x] AC-2: No engine-side component is named "veneer": `hearth/veneer/{server,protocol}.py` are
      gone, `hearth/gateway/{server,protocol}.py` provide them, and the class is `Gateway`; a
      test asserts this (satisfies PLM-007 FC-2).
- [x] AC-3: Both modules and all three renamed test modules were moved with `git mv`, so history
      follows the files.
- [x] AC-4: Behavior is unchanged: the full existing test suite passes with no test's *intent*
      altered — only names, imports, and the one log string moved. No change to the wire format,
      the safety whitelist in `protocol.serialize`, session handling, or `ping_interval=None`.
- [x] AC-5: A `grep -rniI veneer` over the repo is recorded as molt evidence, with every
      remaining hit accounted for as belonging to `client.py`, the `veneer:` config section,
      `pyproject.toml:14`, user-facing docs — each owned by a named later feather — or the
      preserved malformed-frame provenance literal (kept per AC-4 / FTHR-025). No unaccounted
      hit remains.
- [x] AC-6: `hearth/logging_setup.py:52` and `tests/test_console_formatter.py:111` no longer
      name a path that does not exist.
- [x] AC-7: `hearth/config.py`, `config/**`, `packaging/build.sh`, and `tests/test_config.py`
      are untouched by this feather, leaving FTHR-022 free to run concurrently.
- [x] AC-8: `ruff check .` is clean and the full existing test suite passes.
