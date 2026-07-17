# Molt evidence — FTHR-032: Registry selection targets audio config; manifest.py defect fix

Worktree: `.../scratchpad/FTHR-032`  ·  Branch: `feather/FTHR-032-registry-manifest-fix`
Test command (from worktree root):

```
/home/penguin/source/hearth/.venv/bin/python -m pytest -q tests/test_manifest_select.py
```

New test module: `tests/test_manifest_select.py`. Changed: `training/manifest.py`.

---

## AC-1

Test-first on a **live defect**. The tests were written first and run against the
**unchanged** `training/manifest.py`. The absent-wake-section case and the two
write cases raise the actual, current **`StopIteration`** from the bare `next()` in
`_write_model_paths` (the real defect — the module's `CONFIG` looked for a `wake:`
section that the audio config never has); the repoint test fails on the stale
`CONFIG = Path("config.yaml")`. The standalone guard (`test_manifest_stays_standalone`,
`Fails before: n/a`) passes unmodified.

Pre-implementation run (verbatim, against unchanged code):

```
FFFF.                                                                    [100%]
=================================== FAILURES ===================================
_ test_select_on_config_without_wake_section_raises_today_then_errors_cleanly __
...
    with pytest.raises(SystemExit) as exc:
>           mod.cmd_select(select_ns("vesta"))
tests/test_manifest_select.py:119:
training/manifest.py:129: in cmd_select
    _write_model_paths(paths)
    def _write_model_paths(paths: list[str]) -> None:
        """Replace wake.model_paths in config.yaml, preserving comments/order."""
        lines = CONFIG.read_text().splitlines()
>       start = next(i for i, ln in enumerate(lines) if ln.rstrip() == "wake:")
E       StopIteration
training/manifest.py:142: StopIteration
_____________ test_select_writes_path_and_threshold_from_registry ______________
...
>       start = next(i for i, ln in enumerate(lines) if ln.rstrip() == "wake:")
E       StopIteration
training/manifest.py:142: StopIteration
______________ test_select_targets_audio_config_not_engine_config ______________
>       assert fresh.CONFIG == Path("config/audio.yaml")
E       AssertionError: assert PosixPath('config.yaml') == PosixPath('config/audio.yaml')
tests/test_manifest_select.py:145: AssertionError
______________ test_multiple_models_each_keep_their_own_threshold ______________
...
>       start = next(i for i, ln in enumerate(lines) if ln.rstrip() == "wake:")
E       StopIteration
training/manifest.py:142: StopIteration
=========================== short test summary info ============================
FAILED tests/test_manifest_select.py::test_select_on_config_without_wake_section_raises_today_then_errors_cleanly
FAILED tests/test_manifest_select.py::test_select_writes_path_and_threshold_from_registry
FAILED tests/test_manifest_select.py::test_select_targets_audio_config_not_engine_config
FAILED tests/test_manifest_select.py::test_multiple_models_each_keep_their_own_threshold
4 failed, 1 passed in 0.05s
```

Post-implementation run: see the passing run recorded under AC-9 (whole module green).

---
## AC-2 — path + threshold from the registry (FC-4)

`test_select_writes_path_and_threshold_from_registry`. `select vesta` writes
`{path, threshold}` with the threshold taken from `models.json`; a round-trip read
returns the real `vesta` value `0.77` and the stale `0.5` default is gone.

Post-fix demo of the written `config/audio.yaml`:

```
wake_models:
  - path: models/wake/vesta.onnx
    threshold: 0.77
  - path: models/wake/prometheus.onnx
    threshold: 0.61
```

`_read_wake_models()` round-trips to `[("models/wake/vesta.onnx", 0.77)]` for the
single-model case (asserted by the test).

## AC-3 — targets audio config, not the engine config (FC-13 repoint)

`test_select_targets_audio_config_not_engine_config`. The module constant is now
`CONFIG = Path("config/audio.yaml")` (asserted directly — this is the line that
failed before). The test also writes an `engine.yaml`, runs `select`, and asserts
its bytes are unchanged. The write also preserves the surrounding `engine:` /
`endpoint:` sections and blank-line separators (see the AC-2 demo).

## AC-4 — absent wake section: clear error, no traceback (FC-13)

`test_select_on_config_without_wake_section_raises_today_then_errors_cleanly`.
Before: unhandled `StopIteration` (see AC-1). After: a `SystemExit` (printed as a
one-line message, no traceback, when run as the script) naming both the section
and the file:

```
error: no 'wake_models:' section in <file>. Create it by copying
config/defaults/audio.yaml to <file>, then re-run select.
```

The test asserts the message contains `wake_models` and `audio.yaml`.

## AC-5 — per-model thresholds, no shared threshold (FC-3, writer side)

`test_multiple_models_each_keep_their_own_threshold`. Selecting `vesta` +
`prometheus` writes two entries carrying `0.77` and `0.61` respectively; the test
asserts two distinct thresholds (`len(set(...)) == 2`). See the AC-2 demo output.

## AC-6 — manifest stays standalone (no hearth import)

`test_manifest_stays_standalone` loads `manifest.py` in a **clean subprocess** and
asserts no `hearth.*` module is in `sys.modules` (the test process itself imports
hearth via conftest, hence the subprocess). It passes unmodified.

Guard verified to actually catch a violation: injecting `import hearth` into a copy
and running the same check exits non-zero with `AssertionError: ['hearth']`.

No YAML library was needed — the nested `{path, threshold}` shape is written with
the module's existing stdlib line-editing approach, so **no dependency was added**
and the runtime is not imported.

## AC-7 — produces FTHR-028's schema, defines none

`select` writes values into the existing `wake_models: [{path, threshold}]` list
whose schema is defined only in `hearth/audio/config.py` (`WakeModel`, FTHR-028).
This feather touches neither `hearth/audio/` nor `config/audio.yaml`'s schema
shape — it writes values by construction. The shape was sufficient; no finding
raised against FTHR-028.

## AC-8 — diff scope

Only `training/manifest.py` (changed) and `tests/test_manifest_select.py` (added)
— wave 2 stays disjoint from FTHR-029/030/031. `git status` at commit confirms.

## AC-9 — ruff clean, full suite green

```
$ ruff check .
All checks passed!

$ python -m pytest -q
146 passed in 1.13s
```

---

### Gate notes

- **Stale env-var escape hatch removed.** The old module docstring advertised
  `HEARTH_WAKE__MODEL_PATHS='[...paths...]'` as a no-file-edit equivalent. That key
  referenced a `wake` section the audio config never has, and the shape is now a
  list of `{path, threshold}` dicts (not a bare path list), so the old env var is
  stale. I removed it rather than invent a new env contract, since asserting the
  audio surface's env override would require reading/relying on `hearth/audio/`
  (FTHR-028) and risk defining a shape this feather must not define.
- **`training/README.md` still says `config.yaml` / `wake.model_paths`** (lines
  ~54, 71, 74). Updating it is out of this feather's scope (AC-8 restricts the diff
  to `manifest.py` + its test); flagging the doc drift for a follow-up.
- **Bare slug-on-disk now errors instead of silently selecting.** A slug whose
  `.onnx` exists but has no manifest entry has no threshold to write, so `select`
  emits a clear "record it with upsert first" error. This is a deliberate
  consequence of FC-4 (threshold is required) — noted for visibility.
