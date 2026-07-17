# Molt evidence — FTHR-025: Surface provenance on logged turns

Worktree: `/tmp/claude-1000/-home-penguin-source-hearth/69bd3e55-6685-474d-a6a3-120622bc7c54/scratchpad/FTHR-025`
Branch: `feather/FTHR-025-surface-provenance`

Test runner (worktree gotcha): the worktree has no `.venv`; run the repo venv's
python **from the worktree root** so `import hearth` resolves to the worktree,
not the editable install of main:

```
cd <worktree> && /home/penguin/source/hearth/.venv/bin/python -m pytest ...
```

## AC-1

The tests named in the spec's Tests section were written first and run against
the **unchanged** source. Each failed for the expected reason (the surface
feature is absent): `send_turn` takes no surface, `run_turn` takes no surface,
and `parse_request` does not require it.

### Pre-implementation FAILING run (verbatim)

Command:

```
python -m pytest \
  tests/test_gateway.py::test_turn_logged_with_originating_surface \
  tests/test_gateway.py::test_turns_from_different_surfaces_are_distinguishable \
  tests/test_loop.py::test_engine_does_not_branch_on_surface_value \
  tests/test_loop.py::test_run_turn_requires_surface \
  tests/test_gateway_errors.py::test_frame_without_surface_is_rejected_as_malformed
```

Failure reason per test (verbatim excerpts):

```
E               TypeError: send_turn() takes 2 positional arguments but 3 were given
tests/test_gateway.py:87: TypeError        # test_turn_logged_with_originating_surface
tests/test_gateway.py:105: TypeError       # test_turns_from_different_surfaces_are_distinguishable

E       TypeError: Loop.run_turn() got multiple values for argument 'emit'
tests/test_loop.py:275: TypeError          # test_engine_does_not_branch_on_surface_value[audio]
tests/test_loop.py:275: TypeError          # [telegram]
tests/test_loop.py:275: TypeError          # [kiosk-42]
tests/test_loop.py:275: TypeError          # [ANYTHING_AT_ALL]
tests/test_loop.py:275: TypeError          # [z9$_weird]
tests/test_loop.py:275: TypeError          # [🎙️]

>       with pytest.raises(TypeError):
E       Failed: DID NOT RAISE TypeError    # test_run_turn_requires_surface
                                           # (surface param absent -> the call is currently valid)

>       assert replies[0] == {"type": "error", "turn_id": "", "message": "malformed request"}
E       AssertionError: {'message': 'the turn failed'} != {'message': 'malformed request'}
tests/test_gateway_errors.py:239: AssertionError   # test_frame_without_surface_is_rejected_as_malformed
                                                   # (parse_request ignores the missing surface;
                                                   #  the frame reaches run_turn instead of the
                                                   #  existing malformed-frame path)
```

Full target-suite summary pre-implementation (existing call sites also fail
first with the missing-argument error — step 2 working as intended):

```
20 failed, 13 passed in 0.46s
```

The 20 failures = the 5 new named tests (11 test items incl. 6 parametrizations)
+ the existing call sites in test_gateway.py / test_gateway_errors.py /
test_e2e_gateway.py that now pass a surface and therefore fail against unchanged
source with `send_turn()`/`run_turn()` arity errors.

### Post-implementation PASSING run

The five named tests (10 items incl. 6 parametrizations of
`test_engine_does_not_branch_on_surface_value`):

```
python -m pytest \
  tests/test_gateway.py::test_turn_logged_with_originating_surface \
  tests/test_gateway.py::test_turns_from_different_surfaces_are_distinguishable \
  tests/test_loop.py::test_engine_does_not_branch_on_surface_value \
  tests/test_loop.py::test_run_turn_requires_surface \
  tests/test_gateway_errors.py::test_frame_without_surface_is_rejected_as_malformed
-> 10 passed in 0.05s
```

## AC-2

Each logged turn records its originating surface as the `user_input`
provenance. `hearth/loop.py::run_turn` appends `user_input` with `surface`
(was the `"user"` constant).

- `tests/test_gateway.py::test_turn_logged_with_originating_surface` — a turn
  declaring `chat` is logged with `chat` provenance.
- `tests/test_gateway.py::test_turns_from_different_surfaces_are_distinguishable`
  — two turns declaring `audio` and `chat` yield provenances `["audio", "chat"]`
  (`len(set(...)) == 2`), the literal PLM-007 FC-8/AC-8 requirement.

Both PASS post-impl; both FAILED pre-impl (see AC-1).

## AC-3

`run_turn(self, session_id, turn_id, transcript, surface, emit=null_sink)` —
`surface` is required with no default (it precedes the only defaulted param,
`emit`). `tests/test_loop.py::test_run_turn_requires_surface` asserts
`run_turn("s1","t1","hello")` raises `TypeError`. Pre-impl that call was valid
(DID NOT RAISE — see AC-1); post-impl it raises. PASS.

## AC-4

**The engine does not branch on the surface value.** Two forms of evidence:

1. Test — `tests/test_loop.py::test_engine_does_not_branch_on_surface_value`,
   parameterized over arbitrary strings
   `["audio", "telegram", "kiosk-42", "ANYTHING_AT_ALL", "z9$_weird", "🎙️"]`
   (values no real surface would send). Each runs the same turn under a
   baseline surface (`chat`) and the arbitrary one, asserting identical answer,
   identical backend request bodies, identical emitted events, and identical
   log events **except** the `user_input` provenance. All 6 PASS.

2. Diff read (a green suite alone does not satisfy AC-4). The entire engine
   change to `hearth/loop.py` is:

   ```
   +        surface: str,
            emit: EventSink = null_sink,
        ) -> str:
   -        self._log.append(session_id, turn_id, "user_input", "user", {"text": transcript})
   +        # ... comment ...
   +        self._log.append(session_id, turn_id, "user_input", surface, {"text": transcript})
   ```

   The value is passed into `append` and nothing else. A grep for any
   comparison/branch on a surface value across the engine + gateway
   (`surface ==`, `if surface`, `.startswith`, `match`, `in [...]`, etc.)
   returns **NONE FOUND**. There is no enum/allowlist of surfaces anywhere.

## AC-5

A surface declares its own identity in exactly one place. The base contract
`hearth/veneers/base.py::send_turn` takes `surface` with **no default** — it
does not name any surface itself — and `hearth/veneers/chat/__main__.py`
declares `"chat"` at its single `send_turn` call site. A new surface (e.g.
`audio`) names itself the same way without touching the engine or the contract.
Exercised by the gateway/e2e tests that pass `chat`/`audio` through
`send_turn`.

## AC-6

A frame omitting `surface` takes the **existing** malformed-frame path.
`parse_request` reads `data["surface"]`; a missing key raises `KeyError`, which
`server.py`'s existing `except (json.JSONDecodeError, KeyError, TypeError)`
handler catches — the same curated `"malformed request"` reply, content never
echoed, connection kept alive. No second rejection path and no wire default
were added.

`tests/test_gateway_errors.py::test_frame_without_surface_is_rejected_as_malformed`
sends a surface-less frame with `"secret content"`, asserts the reply is exactly
`{"type":"error","turn_id":"","message":"malformed request"}`, the content is
not echoed, the follow-up well-formed frame is served normally on the same
connection, and exactly one error event is logged with the existing `veneer`
provenance. Pre-impl the frame reached `run_turn` and produced
`"the turn failed"` (see AC-1); post-impl it is rejected as malformed. PASS.

## AC-7

`hearth/memory/log.py` is unchanged — `git status --porcelain hearth/memory/log.py`
returns empty. The existing `provenance` column and `append(session_id,
turn_id, type, provenance, payload)` signature carry the feature; `EventLog`
remains append-only.

## AC-8

The engine's own provenance values are unchanged: `server.py` still logs
`"veneer"` for a malformed frame and `"loop"` for a turn error (grep confirms
both literals present, untouched). The turn-error `"loop"` provenance is the
engine speaking about itself, not a surface. Only the `user_input`
constant `"user"` → `surface` changed.

## AC-9

`tests/test_gateway_concurrency.py` and `tests/conftest.py` are untouched by
this feather — `git status --porcelain` and `git diff --stat HEAD` for both
return empty. FTHR-026 remains free to run concurrently. Any fixture needed by
new tests was added in the test module that uses it (e.g. `_run_turn_capturing`
in `test_loop.py`, `_user_input_provenances` in `test_gateway.py`).

## AC-10

`ruff check .` → `All checks passed!`. Full suite:

```
python -m pytest   ->  129 passed in 1.00s
```
