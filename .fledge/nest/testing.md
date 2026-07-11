---
generated: 2026-07-10T22:45:49Z
commit: ce70f988da5255908dc6a9bb3dc26206b5e57b36
agent: fledge-forager
fledge_version: 0.3.0
---

# Testing

Test frameworks, run commands, and current test coverage as observed from tracked files. Coverage is thin because the runtime source tree is absent.

## Framework & commands

- `pytest`, configured with `asyncio_mode=auto` in `pyproject.toml` — async tests need no `@pytest.mark.asyncio` decorator.
- Run all: `pytest`. Run one: `pytest path/to/test_x.py::test_name`.
- Lint (not tests, but part of the same quality gate): `ruff check .`, line-length 100.
- Dev install: `pip install -e '.[dev]'` (pytest, pytest-asyncio, ruff).

## Current coverage

No test files exist in any of the three scanned modules (root, training, models/.github/pluma). No `tests/` directory, no `test_*.py` files were found. This tracks with the mid-restart state: the runtime package (`assistant/`) and TUI (`tui/`), which would hold the actual test suites, are absent from disk.

## Training pipeline: no automated tests, manual smoke workflow instead

`training/` has no pytest/unittest coverage. Its own quality-gate mechanism is a `--smoke` flag on `train.py`/`train_batch.py`: a fast, shrunken end-to-end run (per `training/README.md`, smoke overrides reduce to ~200 samples / 50 steps) used as a plumbing-validation pass rather than a unit-test suite. Trained-model quality itself is gated numerically, not by tests: `models/wake/models.json`'s `gate_passed` field records whether `optimal_fpph <= target_fp_per_hour` from the eval step.

## CI-level verification

`.github/workflows/release.yml` runs a smoke test on the built binary as part of the release matrix job: invokes `--version` and a DEBUG-level import check, then inspects the first ~40 lines of output to catch hard failures from PyInstaller freezing. This is a packaging-integrity check, not application test coverage.

## Test-first process convention (from CLAUDE.md / fledge taxonomy)

The repo's development process (see `domain.md`) mandates test-first commits: tests are written and shown failing before implementation (`FTHR-xxx: test-first — … tests`), and a reviewer independently verifies each acceptance criterion before a feather is marked "fledged." This is a process convention to follow once runtime code returns, not evidence of existing test files.

## Open Questions

- Where will runtime tests live once `assistant/`/`tui/` are restored (likely `assistant/tests/`, `tui/tests/`, or top-level `tests/`) — no precedent exists yet.
- Whether the training pipeline is expected to gain pytest coverage or will remain smoke-run-only.
