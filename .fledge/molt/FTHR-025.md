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

<!-- filled in after implementation -->

## AC-2

<!-- filled after impl -->

## AC-3

<!-- filled after impl -->

## AC-4

<!-- filled after impl -->

## AC-5

<!-- filled after impl -->

## AC-6

<!-- filled after impl -->

## AC-7

<!-- filled after impl -->

## AC-8

<!-- filled after impl -->

## AC-9

<!-- filled after impl -->

## AC-10

<!-- filled after impl -->
