# Claude Code — fledge team-loop piping

Harness runtime behavior for fledge's Tier C team loop on Claude Code. The workflow *logic* (brooder/skua roles, fix loop, merge gating, pool sizing, recovery steps) lives in the agent-neutral core skill at `.fledge/skills/fledge-orchestrate/implementation.md`; this file covers only how Claude Code realizes the piping. For each primitive's mechanism mapping, see `fledge-adapter.md` in this directory.

## Teammate display (tmux)

`fledge init` wrote `.claude/settings.json` with `teammateMode: tmux` and `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`. Teammates (brooders and skuas) run in their own tmux panes so you can watch them work.

**Precondition:** the session is inside tmux (`test -n "$TMUX"`). If not, split-pane teammate display is unavailable. `implementation.md` §1 surfaces this via a `confirm-gate`: stop and restart inside tmux (recommended), or proceed degraded with in-process teammates (no panes; teammates still run, you just can't watch them in split view).

## Spawning and addressing teammates

- Spawn a teammate of a given agent type (e.g. `fledge-brooder`) named per the penguin-species scheme in `implementation.md` §3.1. The teammate's agent definition (`.claude/agents/fledge-<role>.md`) is its system prompt; the spawn prompt you pass is its task context. Both are the teammate's entire context — it inherits no conversation history.
- Address a teammate by name via `SendMessage`. A teammate may go idle; idle is not completion. It stays alive and addressable until you request its shutdown by name.
- Teammates inherit your permission mode at spawn. Brooders must edit files and run tests unattended in their panes — `implementation.md` §1 surfaces the current mode via a `confirm-gate` and asks whether to proceed or stop while the user switches to a mode without per-action prompts (e.g. `acceptEdits`). Without this, brooder panes stall awaiting approvals.

## The team task list

You are the **sole writer** of the shared team task list. Create one team task per dispatched feather titled `FTHR-###: <title>`, assigned to that brooder teammate, state in-progress. Workers never create, claim, or update entries. Mark a task completed yourself when its feather merges green. The task list is a visibility mirror only; spec frontmatter is the source of truth and wins on any disagreement.

## Recovery after resume

`/resume` and `/rewind` do not restore teammates — after a resume, no teammate from the transcript exists, regardless of what your notes say. `implementation.md` §6 is the recovery procedure; on Claude Code specifically:

1. Treat all remembered teammates as gone; clear the roster.
2. Inventory reality: `git worktree list`, feather branches, `fledge broods` (owner, branch, pid-alive), `fledge vee`. Resume set = held lock + surviving worktree.
3. Respawn a fresh brooder teammate (a new species is fine) into the **existing** worktree and branch; its spawn prompt must say partial work may exist.
4. Respawn the skua pool at `ceil(active brooders / 3)` (min 1) and reassign round-robin.
5. Reconcile the team task list against spec frontmatter.

Manual reconstruction via `fledge vee` + `fledge broods` + `git worktree list` is the resume method; `/resume` does not restore the team.

## Skill loading

The core skills live at `.fledge/skills/` (fledge-owned, committed). Claude Code only discovers project skills under `.claude/skills/`, and it follows symlinked skill directories, so `fledge init` creates one symlink per core skill (e.g. `.claude/skills/fledge-orchestrate` → `../../.fledge/skills/fledge-orchestrate`).

(One pointer to the single source — do not copy the skill into `.claude/skills/`; that creates the duplicate `fledge init`'s guard refuses. Symlinks there are recognized and left alone.)
