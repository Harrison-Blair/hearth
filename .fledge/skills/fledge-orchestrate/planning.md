# Planning phase

Turns a feature request into hatched plumages and implementable feathers, grounded in fresh repository context. Four steps, in order. The user is interrogated throughout — this phase runs in the main session and must stay interactive; only context gathering is delegated.

## 1. Freshness gate

- If `.fledge/nest/index.md` does not exist → go to step 2.
- Otherwise compare the `commit` in its frontmatter to `git rev-parse HEAD`:
  - Equal → context is fresh; skip to step 3.
  - Different → summarize the staleness (`git log --oneline <commit>..HEAD`: how many commits, which areas changed) and run a `confirm-gate` (decision): regenerate context, or proceed with existing context. Respect their choice.

## 2. Gather context (when needed)

This step is **capability-conditional** on the `spawn-worker` primitive.

- **If you provide `spawn-worker`:** spawn a `fledge-forager` worker. A forager self-orchestrates `fledge-context-scout` workers per the forager protocol at `foraging.md` in this skill's directory (one scout per module, parallel). See your adapter's map for how `spawn-worker` is realized in your harness. Wait for the forager's final message, then verify `.fledge/nest/index.md` exists and its `commit` matches HEAD before continuing. Relay the forager's coverage notes to the user.
- **If you do not provide `spawn-worker`:** gather the context yourself in the main session — read the repo's modules and synthesize the eight concern documents into `.fledge/nest/` plus `index.md` following the conventions at `templates/context-doc.md` and the forager pipeline in `foraging.md` (you perform both the forager's and the scout's roles, sequentially). The output set is the same either way.

## 3. Plumage interrogation

1. Read `.fledge/nest/index.md`; load the concern docs whose `Read this when:` lines match the feature request (typically `modules.md`, `architecture.md`, `domain.md`).
2. If the request contains multiple features, split it into separate plumages, one per concern — each plumage must stand alone with its own user stories and criteria. Present the proposed breakdown (titles + one-line scopes) and run a `confirm-gate` (review) on it before authoring anything.
3. Author plumages **one at a time**. For the current plumage only, run the interrogate protocol from the `fledge-interrogate` skill (load `.fledge/skills/fledge-interrogate/SKILL.md`): one question at a time, recommended answer first, facts looked up rather than asked, every decision put to the user. Walk the branches: scope and motivation, user stories, functional criteria, acceptance criteria, out-of-scope, priority.
4. When that plumage's tree is resolved, **draft** the full file (frontmatter — with the prospective next `PLM-###` ID — plus the body sections filled from the interrogation) and run a `confirm-gate` (review) on the full draft. On "Make changes", revise the draft and re-gate; no file is written. On "Accept", create the file with `fledge new plumage --title "<title>" --priority <P0-P3>` (it allocates the real ID, names the file, fills the frontmatter), then write the interrogation's outcome into the body sections, and run `fledge status PLM-### hatched`.
5. Only then move to the next plumage in the breakdown and repeat from 3. Do not proceed to feathers until every plumage in the breakdown is hatched (or the user defers some explicitly).

## 4. Feather interrogation

Run this step once per hatched plumage, completing one plumage's feathers before starting the next.

1. For the current plumage, continue interrogating — still one question at a time — over the decomposition: feather boundaries, ordering and blocking dependencies, priorities, which modules each feather touches (cite the context docs; load more of them as needed), how each feather's behavior will be tested (framework, test location, what each test pins down), and whether any feather needs human oversight during implementation (`oversight: during` — the user participates while the feather is built, with the orchestrator relaying decision checkpoints between the implementer and the user; `oversight: merge` — the user signs off on the reviewed diff before it merges; omitted — fully autonomous).
2. Structure the decomposition around **tracer bullets**: the first feather(s) build a thin, working end-to-end slice through every layer the feature touches — minimal but real and verifiable, proving the architecture — and later feathers widen that slice (more cases, robustness, polish). Prefer this over layer-by-layer feathers that only integrate at the end; each completed feather should leave the system demonstrably working. Make the tracer slice the root of the `depends_on` graph.
3. Decompose for **parallel implementation**: wherever the tracer-bullet ordering allows, shape feathers so independent workers can implement them concurrently — disjoint files/modules per feather, explicit interfaces (types, function signatures, file contracts) defined at the boundaries so parallel work composes, and `depends_on` reserved for true ordering constraints rather than shared-file conflicts. When two candidate feathers would touch the same files, either merge them or move the shared surface into an earlier feather both depend on.
4. Every feather must be test-driven and its design testable. Each feather file's Tests section names the tests that prove its behavior, and its acceptance criteria require the test-first cycle: tests written first, observed FAILING against the unchanged code for the expected reason, then the implementation corrected until they pass. Reject feather boundaries whose behavior can't be pinned down by a test, and shape the Approach so the code exposes the seams those tests need.
5. Propose the decomposition as an outline (feather titles + dependency graph, flagging which feathers can run in parallel), refine it through the interrogation, and close with a `confirm-gate` (review) on the final shape.
6. Author the feathers **one at a time**, in dependency order: for each, **draft** the full file (frontmatter — prospective next `FTHR-###` ID, plumage link, `depends_on`, `oversight`, priority — plus the body sections: Description, Affected Modules, Approach, Tests, Acceptance Criteria as unchecked `- [ ] AC-N: …` boxes) and run a `confirm-gate` (review) on the full draft. On "Make changes", revise the draft and re-gate; no file is written. On "Accept", create it with `fledge new feather --title "<title>" --plumage PLM-### [--depends-on FTHR-a,FTHR-b] [--priority <P>] [--oversight merge|during]` (it allocates the ID, links the plumage, and sets the initial pipping/egg hint from the dependency statuses — that hint is authoring-time only; the implementation phase recomputes dispatch readiness from `depends_on` completion and never writes `egg`→`pipping` back), then write the body sections into the created file. To adjust an existing feather's frontmatter, use `fledge set` (priority, oversight, depends_on, title) — never hand-edit fields the CLI can write.
7. After the last feather, run `fledge preen` and fix every finding before closing. Close by listing the created files, the dependency waves (`fledge vee`), and the ready-to-start feathers (`fledge ready`). Offer to start the implementation phase on the ready feathers.
