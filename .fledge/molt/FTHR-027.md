# FTHR-027 molt evidence — Documentation and vocabulary pass

Docs-only feather. No prose unit tests exist and inventing one would be theatre
(spec Tests section). Verification is: (a) a `grep -rniI veneer` accounting over
all docs with every remaining hit deliberate, (b) executing every command in
`MANUAL_SMOKE.md`, and (c) the existing suite + ruff staying green.

Files touched: `README.md`, `CLAUDE.md`, `MANUAL_SMOKE.md`, `pyproject.toml:14`
(the `websockets` comment only). Nothing under `.fledge/` except this evidence
file. Worktree venv: `.venv` created with `pip install -e .` (base deps), so
`import hearth` and the `hearth`/`hearth-chat` console scripts resolve to the
worktree tree.

## AC-1

Documentation now describes the engine, the `chat` veneer, how each is run and
configured, and the settled vocabulary. Concrete edits:

- **Vocabulary — "veneer" = a user-facing program, "gateway" = the engine's
  channel:**
  - `README.md:15` status table: `WebSocket "veneer" control surface` →
    ``hearth` engine (WebSocket **gateway**) + `hearth-chat` **veneer**`.
  - `README.md:42-49` interaction paragraph + diagram: rewritten to "you talk to
    the engine through a **veneer** … the engine exposes an asyncio WebSocket
    **gateway**"; diagram node `client ⇄ veneer` → `hearth-chat (veneer) ⇄ gateway`.
  - `CLAUDE.md:14`: `WebSocket "veneer" control surface` → `WebSocket **gateway**
    control surface reached by separate **veneer** programs (starting with
    `hearth-chat`)`.
  - `CLAUDE.md:75` request path: `` `Veneer` (WebSocket server, `veneer/`) `` →
    `` a **veneer** … ⇄ `Gateway` (WebSocket server, `gateway/`) ``.
  - `CLAUDE.md:98` seam: `**`veneer/`**` → `**`gateway/`**` (the engine's server),
    plus a new `**`veneers/`**` seam for the user-facing surfaces.
  - `MANUAL_SMOKE.md:1` title: `hearth spine (veneer + loop + router + tools)` →
    `hearth spine (gateway + loop + router + tools)`.
- **Running each component:** `hearth run` (engine) and `hearth-chat` (chat
  veneer) documented in README Quickstart/FAQ, CLAUDE.md, and MANUAL_SMOKE.md —
  and executed live under AC-3.
- **Config layout:** README "Configuration" and CLAUDE.md "Configuration model"
  rewritten from the superseded two-file (`config.yaml` / `default-config.yaml`)
  model to `config/engine.yaml` + `config/defaults/engine.yaml`, `config/chat.yaml`
  + `config/defaults/chat.yaml`, one shared facility
  (`hearth/config.py::resolve_config_path`).

No documentation describes the superseded single-surface arrangement where a
"veneer" is the WebSocket server. Satisfies PLM-007 FC-15 / AC-14.

## AC-2

`grep -rniI veneer` over all documentation (`*.md`, excluding `.fledge/`), plus
`pyproject.toml`. Final state — every hit is a **user-facing program** reference;
none describes the engine's channel as a veneer:

```
MANUAL_SMOKE.md:33: run the chat veneer and drive it interactively   (chat = a veneer)
MANUAL_SMOKE.md:65: ## 3. Chat veneer as an installed console script (FTHR-024 AC-4)
MANUAL_SMOKE.md:69: after any change to the chat veneer or its packaging
README.md:15:  `hearth-chat` **veneer**                                (user-facing program)
README.md:42:  You talk to the engine through a **veneer**            (definition of the term)
README.md:44:  the bundled `hearth-chat` veneer connects to it
README.md:49:  hearth-chat (veneer) ⇄ gateway                         (diagram: veneer ≠ gateway)
README.md:131: config for the `hearth-chat` veneer
CLAUDE.md:14:  reached by separate **veneer** programs
CLAUDE.md:60:  config for the `hearth-chat` veneer
CLAUDE.md:81:  a **veneer** (a separate client process, e.g. `hearth-chat`) ⇄ `Gateway`
CLAUDE.md:107: never leak to a veneer
CLAUDE.md:109-111: **`veneers/`** — the user-facing surfaces … `hearth-chat` console veneer
pyproject.toml:14: # gateway server + veneer client                   (comment: distinguishes both)
pyproject.toml:49: hearth-chat = "hearth.veneers.chat.__main__:main"  (entry point; code path)
```

`training/README.md` and `.env.example`: 0 veneer hits. No hit describes the
engine's channel as a veneer; the only engine-channel references now say
**gateway**.

## AC-3

Every command in `MANUAL_SMOKE.md` executed. A **live Ollama** (localhost:11434)
turned out to be available in this environment, so the local spine ran fully
end-to-end — further than the doc assumes. The remote (OpenRouter) tier has no
API key here, the one external prerequisite the doc itself calls out (§4).

**Setup / install.** Ran `python3 -m venv .venv && .venv/bin/pip install -e .`
(base deps) — identical to §3 step 1, and sufficient for the whole spine
(`websockets`+`httpx`+`pydantic` are base deps). Did **not** run `.[all]`: those
extras are roadmap/audio-only, exercised by no spine command, and need the native
system libs the doc lists (portaudio/espeak-ng/etc.). Both console scripts
installed: `.venv/bin/hearth`, `.venv/bin/hearth-chat`.

**§1 step 3 — `hearth run`.** Engine started and bound the gateway:

```
hearth daemon starting
gateway serving host=127.0.0.1 port=8765
server listening on 127.0.0.1:8765
# ss -ltn: LISTEN 127.0.0.1:8765
```

**§1 step 5 — plain question via `hearth-chat`** (the chat-veneer start step —
the one FTHR-024 changed, the whole point of this AC):

```
$ echo "what's 2 plus 2" | .venv/bin/hearth-chat
> [hearth] 4.
chat exit=0
```

Engine log: `orchestrator turn … tier=default model=qwen3:14b` → local Ollama
`200 OK` → `turn summary turn=1 rounds=1 calls=1`. No error line, no crash.

**§1 step 6 — Wikipedia-triggering question** (`who was Ada Lovelace`): the
`…consult` tool_activity line rendered, then a sensible answer, exit 0. The
`consult_brain` call hit the `tool` tier (OpenRouter) → `401 Unauthorized`
(no key), the orchestrator degraded gracefully to a local round-2 answer — the
documented no-key path (§4), not a crash:

```
> …consult
[hearth] Ada Lovelace was a 19th-century mathematician and writer … Analytical Engine …
chat exit=0
# engine log:
consult turn model backend=remote tier=tool model=tencent/hy3:free
POST https://openrouter.ai/api/v1/chat/completions "HTTP/1.1 401 Unauthorized"
llm call tier=tool round=1 FAILED reason=backend error
turn summary turn=1 rounds=3 calls=3 (1 failed)
```

**§2 (remote-tier smoke) — could not fully run:** requires a valid
`HEARTH_LLM__OPENROUTER_API_KEY`, absent here (external prerequisite, §4). Step 5
(inspect the event log) ran; because the tool tier 401'd, the latest
`routing_decision` is the default tier, not `"tier":"tool"`:

```
$ sqlite3 hearth.db "select payload_json from events where type='routing_decision' order by id desc limit 1;"
{"tier": "default", "backend_name": "local", "reason": "chat-turn→default tier"}
```

This is exactly the documented "No OpenRouter key set" environment case, not a
spine bug.

**§3 step 4 — engine DOWN, `hearth-chat`** — a single plain line naming the
host/port, a **non-zero** exit, and **no Python traceback**:

```
$ echo "what's 2 plus 2" | .venv/bin/hearth-chat   # engine not running
cannot reach the hearth engine at 127.0.0.1:8765 -- is it running? start it with `hearth run`.
exit=1
```

Every command that does not require the absent OpenRouter key ran and worked as
written; the two that need it are the documented external prerequisite and are
noted honestly rather than faked.

## AC-4

`CLAUDE.md`'s secrets rule (FTHR-015) survives intact — only the filename it
references changed (`config.yaml` → `config/engine.yaml`). Final text:

```
2. **`.env`** — **secrets only**. This is a hard rule established by FTHR-015: API
   keys live in `.env` (see `.env.example`, `HEARTH_<SECTION>__<PROVIDER>_API_KEY`),
   never in the YAML. Non-secret tunables (models, hosts, thresholds) stay in
   `config/engine.yaml`. Do not add secret fields to the YAML files.
```

The rule ("`.env` only, never the YAML", "do not add secret fields to the YAML
files") is unchanged — not weakened, softened, or dropped. README's Secrets rule
paragraph was likewise preserved with only the filename updated.

## AC-5

`CLAUDE.md`'s config-section list now matches `Settings` after FTHR-024 — no
`veneer` section, `gateway` in its place:

```
Config sections that actually exist (see `hearth/config.py` `Settings`): `llm`,
`gateway`, `tool`, `agent`, `persona`, `conversation`, `storage`, `logging`.
```

Cross-checked against `hearth/config.py` `class Settings` fields: `llm`,
`gateway`, `tool`, `agent`, `persona`, `conversation`, `storage`, `logging` —
exact match, no `veneer`. README's config-section table `veneer` row was likewise
replaced with a `gateway` row.

## AC-6

Architecture description states veneers are separate processes over the wire,
concurrent with isolated conversations, turns logged with the originating surface:

- `CLAUDE.md:109-111` new `**`veneers/`**` seam: "the user-facing surfaces, each
  a **separate process** reaching the engine only over the wire … Multiple veneers
  may run concurrently with isolated conversations, and every turn is logged with
  its originating surface (FTHR-025)."
- `README.md:42-46`: "a **veneer** — a separate client program that reaches the
  engine only over the wire … Multiple veneers can run at once, each with its own
  isolated conversation, and every turn is logged with the surface it came from."

Grounded in the code: `hearth/veneers/base.py` (separate-process client contract,
"no `hearth` engine internals ever cross into a veneer"), `tests/
test_gateway_concurrency.py` (concurrent isolated sessions), and the `surface`
provenance on logged turns (FTHR-025, `send_turn(..., surface)`).

## AC-7

`CLAUDE.md` persona-description lines now say **Vesta**, matching PLM-005 (fledged)
and `tests/test_config.py` (asserts `"You are Vesta."`, and `"calcifer"` absent):

- `carrying the **Calcifer** persona prompt` → `carrying the **Vesta** persona prompt`
- `folds back into Calcifer's voice` → `folds back into Vesta's voice`

Exactly two lines changed — the orphaned persona lines named in the spec. No other
Calcifer→Vesta edits were made (see AC-8).

## AC-8

The known-false **wake-word** lines are **untouched** — verified they still read
"Calcifer" / claim both models exist, and are absent from this feather's diff:

- `CLAUDE.md:8-9` `Wake word: **Calcifer**` — untouched.
- `CLAUDE.md:18` `models/wake/calcifer.onnx` — untouched.
- `CLAUDE.md:124` `manifest.py select` … point `config.yaml` … set `wake.threshold`
  — untouched, **including** its `config.yaml` reference (owned by PLM-008 FC-14/
  AC-14; the deliberate asymmetry with AC-3's config-filename updates).
- `README.md` wake-model claims (`models/wake/vesta.onnx` / `prometheus.onnx`
  "already exist"; the Vesta/Prometheus wake FAQ) — untouched.

`git diff` confirms none of these lines appear in the change set. They remain
owned by PLM-008.

## AC-9

Nothing under `.fledge/` was modified except this new evidence file (the required
deliverable). `git status --short` on the feather branch shows only:

```
 M CLAUDE.md
 M MANUAL_SMOKE.md
 M README.md
 M pyproject.toml
```

plus the new `.fledge/molt/FTHR-027.md`. No fledged spec or prior molt record was
touched.

## AC-10

```
$ .venv/bin/ruff check .
All checks passed!

$ /home/penguin/source/hearth/.venv/bin/python -m pytest -q
132 passed in 1.11s
```

`import hearth` confirmed resolving to the worktree tree. The pyproject comment
edit and the doc prose are read by no test; the suite is unaffected.
