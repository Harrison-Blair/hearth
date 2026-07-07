# FTHR-006 evidence: Persona v2 + canned() template registry

## AC-1

Tests listed in the spec's Tests section were added to `tests/test_persona.py`
first, run against the unchanged `assistant/core/persona.py`, and observed
FAILING for the expected reason (missing `canned`/`_CANNED`, and the v1
"drop the theatrics" rule still present). Implementation followed, and the
same tests were re-run and observed PASSING.

### Pre-implementation (FAILING) — `pytest tests/test_persona.py -q`

```
....F.........FFFFFFFFFFFFFFFFFFFFFFFFF                                  [100%]
=================================== FAILURES ===================================
______ test_persona_v2_drops_the_theatrics_rule_for_deterministic_replies ______

    def test_persona_v2_drops_the_theatrics_rule_for_deterministic_replies():
        # v1's "Routine or deterministic commands: drop the theatrics, just confirm"
        # rule is gone; v2 keeps the voice on deterministic replies instead.
        for strength in ("terse", "expansive"):
            text = persona.persona_segment(strength)
>           assert "drop the theatrics" not in text
E           AssertionError: assert 'drop the theatrics' not in 'You are Cal...to the user.'
E
E             'drop the theatrics' is contained here:
E               commands: drop the theatrics, just confirm.
E               Stay accurate — the persona changes voice, never the facts. This applies ONLY to your final reply to the user.

tests/test_persona.py:55: AssertionError
_ test_canned_disabled_returns_exact_current_plain_string[error_generic-Sorry, something went wrong.] _

key = 'error_generic', plain = 'Sorry, something went wrong.'

    @pytest.mark.parametrize("key, plain", _CANNED_PLAIN.items())
    def test_canned_disabled_returns_exact_current_plain_string(key, plain):
>       assert persona.canned(key, enabled=False) == plain
               ^^^^^^^^^^^^^^
E       AttributeError: module 'assistant.core.persona' has no attribute 'canned'

tests/test_persona.py:317: AttributeError

[... remaining canned()-family tests fail the same way: AttributeError on
persona.canned / persona._CANNED, since neither existed yet ...]

=========================== short test summary info ============================
FAILED tests/test_persona.py::test_persona_v2_drops_the_theatrics_rule_for_deterministic_replies
FAILED tests/test_persona.py::test_canned_disabled_returns_exact_current_plain_string[error_generic-Sorry, something went wrong.]
FAILED tests/test_persona.py::test_canned_disabled_returns_exact_current_plain_string[cant_help-Sorry, I can't help with that yet.]
FAILED tests/test_persona.py::test_canned_disabled_returns_exact_current_plain_string[llm_offline-Sorry, I couldn't reach my language model.]
FAILED tests/test_persona.py::test_canned_disabled_returns_exact_current_plain_string[no_answer-Sorry, I don't have an answer for that.]
FAILED tests/test_persona.py::test_canned_disabled_returns_exact_current_plain_string[unexpected_reply-Sorry, I wasn't expecting a reply.]
FAILED tests/test_persona.py::test_canned_disabled_returns_exact_current_plain_string[update_signoff-Restarting now.]
FAILED tests/test_persona.py::test_canned_enabled_returns_one_of_the_variants[error_generic]
FAILED tests/test_persona.py::test_canned_enabled_returns_one_of_the_variants[cant_help]
FAILED tests/test_persona.py::test_canned_enabled_returns_one_of_the_variants[llm_offline]
FAILED tests/test_persona.py::test_canned_enabled_returns_one_of_the_variants[no_answer]
FAILED tests/test_persona.py::test_canned_enabled_returns_one_of_the_variants[unexpected_reply]
FAILED tests/test_persona.py::test_canned_enabled_returns_one_of_the_variants[update_signoff]
FAILED tests/test_persona.py::test_canned_rotation_is_deterministic_under_a_seeded_rng[error_generic]
FAILED tests/test_persona.py::test_canned_rotation_is_deterministic_under_a_seeded_rng[cant_help]
FAILED tests/test_persona.py::test_canned_rotation_is_deterministic_under_a_seeded_rng[llm_offline]
FAILED tests/test_persona.py::test_canned_rotation_is_deterministic_under_a_seeded_rng[no_answer]
FAILED tests/test_persona.py::test_canned_rotation_is_deterministic_under_a_seeded_rng[unexpected_reply]
FAILED tests/test_persona.py::test_canned_rotation_is_deterministic_under_a_seeded_rng[update_signoff]
FAILED tests/test_persona.py::test_canned_rotation_covers_all_variants_across_draws[error_generic]
FAILED tests/test_persona.py::test_canned_rotation_covers_all_variants_across_draws[cant_help]
FAILED tests/test_persona.py::test_canned_rotation_covers_all_variants_across_draws[llm_offline]
FAILED tests/test_persona.py::test_canned_rotation_covers_all_variants_across_draws[no_answer]
FAILED tests/test_persona.py::test_canned_rotation_covers_all_variants_across_draws[unexpected_reply]
FAILED tests/test_persona.py::test_canned_rotation_covers_all_variants_across_draws[update_signoff]
FAILED tests/test_persona.py::test_canned_unknown_key_raises_key_error - Attr...
26 failed, 13 passed in 0.24s
```

(The 13 pre-existing passes are the untouched v1-era tests before this
feather's new assertions were added; all 26 new/modified assertions fail for
the expected reason: the v2 wording change and the `canned()` API don't
exist yet.)

### Post-implementation (PASSING) — `pytest tests/test_persona.py -q`

```
.......................................                                  [100%]
39 passed in 0.16s
```

## AC-2

v2 blocks (`_CALCIFER_V2_TERSE`, `_CALCIFER_V2_EXPANSIVE`) replace the v1
blocks in `assistant/core/persona.py`. The v1 rule "Routine or deterministic
commands: drop the theatrics, just confirm" is replaced with "Routine or
deterministic commands: still in character — one flavored beat, then the
fact." No `_CALCIFER_V1_*` name survives anywhere in the tree:

```
$ grep -rn "_CALCIFER_V1" assistant/ tests/
no v1 names found
```

Pinned by test `test_persona_v2_drops_the_theatrics_rule_for_deterministic_replies`
(asserts `"drop the theatrics" not in text` and `"flavored beat" in text` for
both strengths) — see AC-1 passing run above.

## AC-3

Every `canned()` key (`error_generic`, `cant_help`, `llm_offline`,
`no_answer`, `unexpected_reply`, `update_signoff`) has 2–3 in-character
variants in `_CANNED` and a persona-disabled plain fallback.

- `error_generic`, `cant_help`, `llm_offline`, `no_answer`, `unexpected_reply`:
  plain fallbacks are byte-identical to the current literals found at these
  call sites (confirmed by grep before writing the registry):
  - `assistant/core/pipeline.py:550,573` — "Sorry, something went wrong."
  - `assistant/core/pipeline.py:554` — "Sorry, I can't help with that yet."
  - `assistant/skills/general.py:38` — "Sorry, I couldn't reach my language model."
  - `assistant/skills/general.py:40` — "Sorry, I don't have an answer for that."
  - `assistant/skills/base.py:64` — "Sorry, I wasn't expecting a reply."
- `update_signoff`: migrates `UpdateSkill`'s existing `_SIGNOFFS` lines
  (`assistant/skills/update.py`) verbatim as the 3 in-character variants.
  `UpdateSkill` previously spoke one of these unconditionally regardless of
  persona state (no plain literal existed pre-persona), so a new terse plain
  fallback — "Restarting now." — was authored for the disabled path; the
  three existing signoff lines are unchanged as the enabled-path variants.

Pinned by test:
- `test_canned_disabled_returns_exact_current_plain_string` (parametrized
  over all 6 keys) — asserts `canned(key, enabled=False) == plain` for the
  exact literal above.
- `test_canned_enabled_returns_one_of_the_variants` — asserts 2–3 variants
  exist and a draw is one of them.
- `test_canned_rotation_is_deterministic_under_a_seeded_rng` — same seed,
  same draw.
- `test_canned_rotation_covers_all_variants_across_draws` — 50 draws from a
  seeded `random.Random` cover the full variant set.
- `test_canned_unknown_key_raises_key_error` — unknown key raises `KeyError`.

All pass in the AC-1 post-implementation run above.

## AC-4

### `pytest` (full suite)

```
$ pytest -q
ss...................................................................... [  8%]
........................................................................ [ 17%]
........................................................................ [ 26%]
........................................................................ [ 35%]
........................................................................ [ 44%]
........................................................................ [ 53%]
........................................................................ [ 62%]
........................................................................ [ 71%]
........................................................................ [ 80%]
........................................................................ [ 89%]
........................................................................ [ 98%]
..........                                                               [100%]
800 passed, 2 skipped, 1 warning in 22.85s
```

### `ruff check assistant tests`

```
$ ruff check assistant tests
All checks passed!
```

### Changed files (scope check)

```
$ git status --porcelain
 M assistant/core/persona.py
 M tests/test_persona.py
```

Only `assistant/core/persona.py` and `tests/test_persona.py` were modified,
per the spec's Affected Modules — no other production file changed.
