# FTHR-037 — Voice acquisition: required config, fetch-if-absent, first-run error

Molt evidence. Test-first: the five listed tests were written and run against the
unchanged surface (no voice check existed) and observed failing for the expected
reason, then implemented until green. All proof here is **offline** — the fetch is
driven by an injected recorder; no network, no real download.

Startup policy, in one place (`hearth/audio/voice.py::ensure_voice`, called from
`hearth/audio/surface.py::main` before serving):

- voice **unset** ⇒ actionable `SystemExit` (non-zero, no traceback) — a config
  problem, not a crash.
- voice **named but absent** ⇒ injected fetch runs, then serving proceeds.
- voice **named and present** ⇒ no fetch.

The voice **name → on-disk artifact** mapping is `models/voices/<name>.onnx`, a
module constant (mirrors `training/manifest.py`'s hardcoded model paths) — it does
**not** touch FTHR-035's `voice` key schema.

## AC-1

Tests written first, run against unchanged code (module `hearth.audio.voice` and
`main()`'s injected seams did not yet exist).

Command:

```
cd <worktree> && /home/penguin/source/hearth/.venv/bin/python -m pytest tests/test_audio_voice.py -q
```

Failing output (pre-implementation) — verbatim:

```
E       ModuleNotFoundError: No module named 'hearth.audio.voice'
tests/test_audio_voice.py:39: ModuleNotFoundError
E       ModuleNotFoundError: No module named 'hearth.audio.voice'
tests/test_audio_voice.py:71: ModuleNotFoundError
E       ModuleNotFoundError: No module named 'hearth.audio.voice'
tests/test_audio_voice.py:88: ModuleNotFoundError
E       ModuleNotFoundError: No module named 'hearth.audio.voice'
tests/test_audio_voice.py:117: ModuleNotFoundError
E           TypeError: main() got an unexpected keyword argument 'fetch'
tests/test_audio_voice.py:153: TypeError
FAILED tests/test_audio_voice.py::test_absent_voice_refuses_to_start_with_actionable_message
FAILED tests/test_audio_voice.py::test_configured_absent_voice_is_fetched_before_serving
FAILED tests/test_audio_voice.py::test_present_voice_is_not_refetched - Modul...
FAILED tests/test_audio_voice.py::test_fetch_is_hermetic_and_injectable - Mod...
FAILED tests/test_audio_voice.py::test_unset_voice_exits_before_serving - Typ...
5 failed, 1 passed in 0.06s
```

The five behavioural tests fail for the expected reason (the module and the
injected `main()` seams do not exist yet). `test_no_voice_listing_subcommand_is_added`
is a **guard** test that passes pre-implementation by design (no such subcommand
exists) and must keep passing after — the spec notes its "Fails before: n/a".

Passing run (post-implementation), same command:

```
......                                                                   [100%]
6 passed in 0.04s
```

All five behavioural tests now pass and the guard test still passes.

## AC-2 — absent voice ⇒ actionable error, non-zero, no traceback

`test_absent_voice_refuses_to_start_with_actionable_message` +
`test_unset_voice_exits_before_serving`. With no voice configured,
`ensure_voice(None, ...)` raises `SystemExit` (the manifest.py `error:`/SystemExit
idiom → prints to stderr, exits non-zero, **no traceback**). The test asserts
`exc.code not in (0, None)` and both message fragments:

- **names the setting**: `"voice"` and `"config/audio.yaml"` present.
- **states how to discover voices**: `"https://"` and `"piper"` present (a
  pointer to the piper voice catalog, not a command).

`test_unset_voice_exits_before_serving` drives `surface.main(...)` with an unset
voice and asserts the injected `serve` seam is never called and nothing is fetched
— the error exits *before* serving. Green (part of the 6 passed above).

## AC-3 — fetch-if-absent, no re-fetch when present

`test_configured_absent_voice_is_fetched_before_serving`: a named-but-absent voice
invokes the injected fetcher exactly once, at `models/voices/<name>.onnx`, and
`ensure_voice` returns that path. `test_present_voice_is_not_refetched`: with the
artifact already on disk the fetcher is **not** called. Both branches proven with a
`RecordingFetcher` double — **no network**. Green.

## AC-4 — injectable seam, hermetic (offline) in CI

`test_fetch_is_hermetic_and_injectable`: `socket.socket` is monkeypatched to raise;
`ensure_voice` still resolves both the absent (fetch via the injected recorder) and
present (no fetch) branches — proving the policy performs no network of its own. The
fetch is the injected `fetch=` seam (default `download_voice`). Green.

## AC-5 — no voice-listing subcommand / flag

`test_no_voice_listing_subcommand_is_added`: scans every `hearth.audio.*` module
source for `list-voices` / `list_voices` / `--voices` / `audition` / `picker` (none
present) and asserts `surface.main` exposes no CLI positional — only keyword-only,
defaulted injection seams for tests. Discovery is a pointer inside the error message
only. Green.

## AC-6 — consumes FTHR-035's `voice` key; no render/play/barge-in

`ensure_voice` reads `settings.voice` (FTHR-035's key; unset ⇒ absent) and does not
redefine it — no change to `hearth/audio/config.py`. The name→artifact mapping is a
module **constant** `VOICES_DIR = models/voices` (mirrors `training/manifest.py`'s
hardcoded model paths), not a schema addition. This feather does not render
(FTHR-036), play or touch a device (FTHR-038), or do barge-in. The only config-shape
question — the **default fetcher's real source** — was raised to the orchestrator as
a finding against the acquisition seam (escalation `fledge-brooder-emperor`,
2026-07-17T21:49Z); resolved by deferring the real download to FTHR-039 (see AC-7),
so no new config field was added.

## AC-7 — scope of what CI proves vs. what FTHR-039 confirms

CI here proves the **startup policy** (unset ⇒ error+exit; named-absent ⇒ fetch;
present ⇒ no-fetch) and the **message content** (setting name + discovery pointer),
all **offline** via the injected fetcher. It does **not** prove a real voice
downloads from a real source, and does not judge whether the message *reads well* —
both are confirmed at the first real run / **FTHR-039's** end-to-end smoke.
`voice.download_voice` (the production fetch seam) is deliberately deferred: until
FTHR-039 wires a real source, a named-but-absent voice surfaces an actionable
instruction rather than a silent no-op or an unprovable network dependency.

## AC-8 — ruff clean, full suite green

```
$ /home/penguin/source/hearth/.venv/bin/python -m pytest -q
172 passed, 1 warning in 2.04s
$ /home/penguin/source/hearth/.venv/bin/ruff check .
All checks passed!
```

(The one warning is the pre-existing `webrtcvad`/`pkg_resources` deprecation from
`test_audio_endpoint.py`, unrelated to this feather.)

