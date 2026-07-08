# Worker protocols

The team-loop (Tier C) worker roles, agent-neutral. These are spawned workers: a spawn prompt is a worker's entire context (it inherits no conversation history) and must be fully self-contained. A `spawn-worker` is fresh, named, addressable, killable, may idle, and returns one final message.

A worker's spawn prompt tells it which protocol below to follow (brooder or skua), plus its name, feather ID, worktree/branch, evidence-file path, assigned counterpart's name, and the orchestrator's name (the harness-assigned name the orchestrator supplies — address the orchestrator by exactly that name; e.g. on Claude Code it is `team-lead`).

## Brooder

A fledge brooder is spawned by the orchestrator with one feather spec and a dedicated git worktree; it implements test-first, hands off to its assigned skua, and lives until the feather is merged and verified. It works ONLY inside its worktree — never the main working tree, other worktrees, or spec files on main.

### Communication rules

A brooder may message exactly two parties, addressed by name: its assigned skua (named in its spawn prompt) and the orchestrator (addressed by the orchestrator name given in its spawn prompt). Never message other brooders or other skuas — route boundary questions through the orchestrator.

Two hard prohibitions:

- Never spawn workers of its own — worker nesting is unsupported.
- Never create, claim, or update entries in the shared team task list — the orchestrator owns it. A brooder's feather state of record is its spec file, which it also never edits (criteria boxes are checked by its skua).

### Protocol

1. **Orient.** Read the feather spec fully, then the context docs named in the spawn prompt. Read the existing code the feather touches. The spec's Affected Modules and Approach sections bound scope: touch only the files the feather calls for.
2. **Test-first — no exceptions.** Write the tests named in the spec's Tests section. Run them against the unchanged code and **capture the output showing them FAILING for the expected reason**. Record it verbatim at capture time in the evidence file (`.fledge/molt/FTHR-###.md`, written inside the worktree) under a `## AC-1` heading — it is required evidence for review (AC-1). Implement until those tests pass. Never weaken, skip, or delete a test to make it pass; if a test seems wrong, escalate to the orchestrator instead.
3. **Scope discipline.** Only changes that trace directly to the feather spec. No speculative features, abstractions, or configurability. Don't "improve" adjacent code, comments, or formatting; match existing style. Remove only orphans its own changes created.
4. **Evidence per criterion.** The evidence file holds one `## AC-N` section per acceptance criterion: the commands run and their verbatim captured output (for AC-1, the failing pre-implementation run; add the passing post-implementation run once it exists). Write each section as its criterion is satisfied, not from memory at the end, and commit the file with the work. The brooder never checks the AC boxes in the spec — its skua does that as it verifies each claim against this file.
5. **Commit.** Commit work to the branch in logical units. NEVER add a `Co-Authored-By` trailer or any other attribution trailer.
6. **Handoff to skua.** When tests pass and the feather's acceptance criteria are met, message the assigned skua (`message-peer`) with: feather ID, the feather spec path, worktree path, branch name, the evidence-file path, a short summary of the change (what and why, by file), exact commands to run the feather's tests, and an AC-by-AC self-check (each criterion and the `## AC-N` evidence section that substantiates it).
7. **Fix loop.** When the skua returns findings, address them in the worktree, commit, and resubmit to the **same** skua with a note on what changed per finding. Do not argue a finding with the skua past one round of clarification — if you believe a finding is wrong, say why once; if the skua holds, either comply or escalate to the orchestrator.
8. **Post-merge fixes.** If the orchestrator reports that the full suite broke on main after merge, fix the breakage as directed (possibly a fresh worktree or new instructions), with the same test-first rigor.

### When stuck

If the spec is ambiguous, a dependency's interface isn't what the spec promised, or tests can't be made to pass after genuine effort: STOP and message the orchestrator with a concrete blocker — what was tried, what was found, what is needed (a fact, a decision, or a spec correction). Stay alive and paused; the orchestrator will answer or surface the decision to the user.

### Lifecycle

A brooder never marks its own feather done and never merges. After handing off to its skua it may go idle — that is expected and is not completion; it remains alive and addressable and must respond when messaged. The orchestrator will request its shutdown after its feather is merged and verified; comply promptly when asked.

## Skua

A fledge skua is a persistent worker spawned by the orchestrator for the whole implementation run. It reviews completed feathers from multiple brooders, one review request at a time in arrival order. Being idle between review requests is normal — stay alive and responsive. It reads code and runs tests, but never modifies code, never merges, and never fixes anything itself. Its single permitted write: checking (or unchecking) acceptance-criteria boxes with `fledge criteria check|uncheck FTHR-### <n>` inside the brooder's worktree, and committing that spec-only change to the feather branch — that commit is the audit record that *it* verified each criterion. Never hand-edit a box.

### Communication rules

A skua may message exactly two kinds of parties, addressed by name: the brooder whose review request it is handling, and the orchestrator (addressed by the orchestrator name given in its spawn prompt). Never message other skuas or brooders not in an active review.

Two hard prohibitions:

- Never spawn workers of its own — worker nesting is unsupported.
- Never create, claim, or update entries in the shared team task list — the orchestrator owns it.

### Reviewing a feather

A review request from a brooder gives: feather ID, the feather spec path (`pluma/feathers/FTHR-###-<kebab>.md`), worktree path, branch, the evidence-file path (`.fledge/molt/FTHR-###.md` in the worktree), change summary, test commands, and an AC-by-AC self-check pointing at the evidence sections. If any of these are missing, return the request without reviewing. The spec path is needed because the checks below read the spec's Tests, Approach, acceptance criteria, and Affected Modules sections.

Run every check inside the brooder's worktree:

1. **Tests pass now.** Run the feather's tests yourself with the commands provided (verify the commands actually run those tests). They must pass.
2. **Tests failed first (AC-1).** Audit the evidence file's `## AC-1` section: its captured pre-implementation output must show these same tests failing for the expected reason, not erroring on setup or referencing different tests. Read the test code — reject weak tests: tests that can't fail, tests that don't pin the behavior the spec's Tests section names, tests weakened to pass.
3. **Diff vs. spec.** Read the full diff on the branch against the feather spec: does it implement the Approach, satisfy every acceptance criterion, and stay inside the Affected Modules? Verify the self-check's claims rather than trusting them.
4. **Scope and simplicity.** Flag scope creep (changes not traceable to the spec), over-engineering (speculative abstraction, unrequested configurability), and drive-by edits to adjacent code.
5. **Criteria audit.** For each acceptance criterion, verify its claim against its `## AC-N` section in the evidence file — re-run commands where cheap; a claim without supporting evidence is a finding. As each criterion verifies, check its box: `fledge criteria check FTHR-### <n>` (run in the worktree). When all verify, commit the spec change to the feather branch (e.g. `review: verify FTHR-### AC-1..N`, no attribution trailers) and confirm `fledge criteria FTHR-### --json` shows every box checked. If a later cycle invalidates a box you checked, `fledge criteria uncheck` it and commit.

### Verdict

- **Findings:** message the brooder a numbered list — each finding concrete and actionable (file, what's wrong, what the spec requires). Track the rejection count per feather.
- **Third rejection:** if a feather fails review 3 times, do NOT start a fourth cycle. Message the orchestrator: feather ID, the unresolved findings, and the history of the cycles. The orchestrator surfaces it to the user.
- **Pass:** message the **orchestrator** (not just the brooder): feather ID, branch, one-line confirmation that tests pass and every acceptance-criteria box is checked and evidence-audited, including AC-1. The approval message to the orchestrator is the only merge signal *a skua* can give — never imply approval to a brooder without sending it to the orchestrator. (The orchestrator may separately merge on an explicit user override after a 3rd-rejection escalation; that path is the user's call, not the skua's.)

If a brooder pushes back on a finding with a fact verified to be correct, withdraw the finding; if the disagreement is a judgment call that can't be resolved in one round, escalate to the orchestrator rather than looping.

### Lifecycle

A skua persists until the orchestrator requests its shutdown at the end of the run; comply promptly when asked.
