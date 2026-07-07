---
id: FTHR-002
title: TUI supervisor survives in-place re-exec
plumage: PLM-001
status: egg
priority: P2
depends_on: [FTHR-001]
oversight: merge
authored: 2026-07-07T02:59:34Z
agent: fledge-orchestrate/planning
fledge_version: 0.1.0
---

# FTHR-002: TUI supervisor survives in-place re-exec

## Description
Closes the one open risk FTHR-001 leaves: PLM-001 FC-7's requirement that, **under the
monitor TUI**, a self-update restart is not mistaken for a crash. When the daemon
re-execs itself in place (`os.execv`, same PID, inherited fds), the supervisor's child
handle and its stdin/stdout pipes should survive transparently — the supervisor should
keep reporting the daemon as *running*, the log/state stream should not EOF, and the
TUI pump should never flip to the `stopped` state at the re-exec boundary.

The forager flagged this as genuinely unverified (`.fledge/nest/architecture.md` →
"Daemon supervision and the restart lifecycle"). This feather **proves it with a real
subprocess test**, and hardens only what the test shows to be broken — the expected
outcome is that `execv` is transparent and little or no production code changes, but
the two known subtleties below are checked rather than assumed.

Depends on FTHR-001 (the restart primitive and its source-mode target must exist to
exercise a realistic re-exec).

## Affected Modules
- **`tests/test_tui_supervisor.py`** — new re-exec tests, in the existing
  real-subprocess style (small `-c`/`os.execv` child scripts; see the current
  `LOOP_CHILD`/`ECHO_CHILD` cases). `.fledge/nest/testing.md` → TUI tests.
- **`tui/supervisor.py`** — `DaemonSupervisor` (`running`, `lines()`,
  `_die_with_parent`). Change only if a test proves a gap. `.fledge/nest/modules.md`
  → tui; `.fledge/nest/entry-points.md` → daemon supervision.
- **`tui/app.py`** — the `_pump()` EOF→`stopped` branch (`tui/app.py:215`) and
  `_restart()`. Touch only if the re-exec is observed to trip the stopped state or a
  mid-restart race is found. `.fledge/nest/modules.md` → tui.

Files are disjoint from FTHR-001's (`assistant/**`), but this feather depends on it
functionally, so it runs after.

## Approach
**Verify first.** The mechanics of `os.execv` — same PID, same open file descriptors
(fds 0/1/2 are not close-on-exec) — mean the supervisor's `asyncio` subprocess handle
should stay valid: no `SIGCHLD` (the process never exits), so `returncode` stays
`None` and `running` stays `True`; and the child's stdout write-end is the same fd
after exec, so the parent's read side never sees EOF and `lines()` keeps yielding.
The TUI pump only sets `stopped` on `lines()` EOF (`tui/app.py:216`), so if `lines()`
doesn't end, the pump never flips. Build a real subprocess test that drives an actual
re-exec through `DaemonSupervisor` and asserts exactly these observables.

**Then harden the two known subtleties, only if a test fails:**
1. **Parent-death signal across self-exec.** `_die_with_parent` arms
   `PR_SET_PDEATHSIG` via `preexec_fn` on the *original* spawn; the daemon's own
   `os.execv` has no `preexec_fn`. A normal `execve` preserves the pdeathsig setting
   (it is cleared only for set-uid/set-gid binaries), so a re-exec'd daemon should
   still be reaped if the TUI dies — but this must be *verified*, not assumed. If it
   does not survive, the fix belongs in FTHR-001's restart primitive (re-arm pdeathsig
   immediately after exec, at daemon startup) — coordinate the boundary rather than
   duplicating it.
2. **Mid-restart race.** If the TUI's `_restart()` (SIGTERM→SIGKILL) fires in the same
   window a voice-triggered self-update re-exec is in flight, define the expected
   outcome (the daemon ends up either cleanly restarted-by-TUI or cleanly
   re-exec'd, never a zombie/double). Prefer documenting + a guard only if the race is
   demonstrably reachable; do not add speculative locking.

**Scope discipline.** This is a verification-and-harden feather. Do not refactor the
supervisor or pump beyond what a failing assertion requires; a green suite with new
tests and zero production changes is an acceptable, even ideal, outcome.

## Tests
Written test-first; each observed FAILING (or, for a pure-verification test,
**meaningfully exercising the re-exec path** so it would fail if the supervisor mis-
handled it) before any change, then passing.

- `test_supervisor_treats_reexec_as_running` — a child prints a marker line, then
  `os.execv`s into a second stage that prints a second marker and idles; drive it via
  `DaemonSupervisor`. Assert `running` is `True` across the transition and `lines()`
  yields both markers with no interposed EOF. (PLM-001 FC-7, TUI side)
- `test_reexec_does_not_signal_stopped` — model the pump's EOF→`stopped` rule: assert
  the re-exec produces no `lines()` termination, so the pump's stopped branch is not
  reached. (FC-7)
- `test_pdeathsig_survives_reexec` — verify the parent-death signal is still armed on
  the re-exec'd process (e.g. orphan the re-exec'd child and assert it is reaped), or,
  if pdeathsig is confirmed cleared, that the coordinated re-arm from FTHR-001 restores
  it. Pins down subtlety (1). (FC-7 robustness)

## Acceptance Criteria
- [x] AC-1: The tests listed above were observed failing (or meaningfully exercising
      the re-exec path) before implementation and pass after.
- [x] AC-2: Under `DaemonSupervisor`, an in-place `os.execv` re-exec keeps `running`
      `True` and does not terminate `lines()`; the TUI pump therefore never enters the
      `stopped` state at the re-exec boundary. (PLM-001 FC-7)
- [x] AC-3: The parent-death signal is confirmed to survive the self-re-exec (or is
      re-armed so a TUI crash still reaps the re-exec'd daemon). (PLM-001 FC-7)
- [x] AC-4: Any production change to `tui/supervisor.py` or `tui/app.py` is limited to
      what a failing test required; no unrelated refactor. (scope discipline)
- [x] AC-5: `pytest` is green and `ruff check` is clean over the touched files.
