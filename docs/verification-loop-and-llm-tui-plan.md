# Verification loop + LLM-identity TUI surfacing — design

A complete, internally-consistent design for two coupled goals:

1. **Reasoning-quality maturity** for the OpenCode Zen-backed LLM: a
   **follow-up verification loop** that checks the model's tool pick and its
   drafted answer *before* speech, with **situation-aware vocalized feedback**
   ("let me double check that", "that's not right") routed through the persona,
   spoken mid-turn so a long thinking turn is not a dead silence.
2. **Surfacing LLM configuration in the TUI**: the Config tab, status panel,
   health loop, and model picker currently hard-assume Ollama and lie when
   `provider=opencode-zen` is the primary. Make them provider-aware.

This doc is the authoritative spec. Every non-obvious decision records its
rationale so an implementer does not undo a deliberate trade. Implementation
order is at the end (§ Phases).

---

## 0. Codebase facts the implementer must know

These were verified by reading the code; do not re-derive them.

- **`assistant/app.py` is the composition root** — the only wiring point.
  Construction order matters: `Orchestrator` is built (app.py:318) *before*
  `VoicePipeline` (app.py:387), which takes the orchestrator as a dep.
  ⇒ A construction-time `speak` callback on `Orchestrator` would need a forward
  reference to `VoicePipeline._speak`. **Use a per-`handle()` callback instead**
  (see §3).
- **`Orchestrator.handle()` is a pure compute→data object.** It returns
  `(SkillResult | None, Skill | None)` at turn-end. It has *no* speech
  mechanism today. The pipeline calls `self._speak(result.speech)` *after*
  `handle()` returns (pipeline.py:553). `_speak` → `_play` → `audio_out.play()`
  does **not** acquire the `AudioArbiter`; it assumes the caller holds it. The
  pipeline holds `arbiter.hold("pipeline")` (or `hold("text")`) for the whole
  turn (pipeline.py:285, 336). ⇒ Passing a speech callback into the orchestrator
  is **deadlock-free**: the arbiter hold covers the whole `handle()` call.
- **`_speak` returns `barged: bool`** — `True` when the wake word fires during
  playback (barge-in cuts it). The orchestrator must **abort the turn** if a
  filler is barged.
- **Persona is a text suffix baked into per-skill system prompts** at
  construction via `with_persona(base, persona_suffix)` (see
  `assistant/core/persona.py`). Its contract: *"Never composed onto
  tool-decision, refine/assess, or any JSON-structured prompt — the persona
  changes how a reply sounds, never which tool runs or the facts stated."*
  `persona_suffix` is built once in app.py:240 and passed to `GeneralSkill`,
  `WeatherSkill`, `WebSearchSkill`, `CalendarSkill`. The orchestrator's
  `_decide`/`_decide_json` calls are persona-free. The verify call is an
  "assess" call ⇒ **persona is forbidden on the verify *judgment* by contract**.
  This design *deliberately relaxes* that contract for the verify call's
  *spoken outputs only* (`feedback`, `rewritten_speech`) — see §2 rationale.
- **`web_search.py` already has a mid-turn speech precedent**: `_say_soon` +
  `progress_updates` toggle + `speaker` callback, gated by a config flag, fires
  at the start of each search round. **The verify filler follows this shape**
  (speak at the start of a re-loop, gated by `verify.spoken_feedback`).
- **The orchestrator's counters** (orchestrator.py:70–135): the loop is
  `for _ in range(self._max_rounds)`; each iteration is one `_decide`.
  `_TOOL_REPEAT_CAP = 2` guards unguided model same-tool stalls
  (`tool_counts[name] > cap` → fallback). `max_tool_rounds=3`.
- **TUI Config tab is driven by `FIELDS` in `tui/config_schema.py`** — the
  documented extensibility seam. Appending a `Field` auto-renders it (label row
  + control). Kinds: `select` (button→`PickerScreen`, has an `options`
  provider), `multiselect`, `number` (`Stepper` with lo/hi/step), `toggle`
  (`Switch`), `text`. Per-field custom pick logic lives in
  `ConfigScreen._open_picker` (config.py) keyed on the field's dotted key.
- **`_select_options` passes `host=self._config.llm.host`** to every options
  provider (app.py:347). Providers share signature `(host=..., **_)`. A
  Zen-aware provider needs `base_url`/`api_key`/`provider`, threaded via the
  same `**_` (backward-compatible).
- **Picking `llm.model` or `tts.model_path` persists to config.yaml + restarts**
  (`_on_model_picked`/`_on_voice_picked`), and **drops the matching
  `ASSISTANT_LLM__*`/`ASSISTANT_TTS__*` env override** so a `.env` entry doesn't
  shadow the new default. This is the established pattern; the four new
  LLM-identity picks follow it.
- **The Zen/fallback providers + their tests are currently UNTRACKED in git**
  (`assistant/llm/opencode_zen_provider.py`, `assistant/llm/fallback_provider.py`,
  `tests/test_zen_provider.py`, `tests/test_fallback_provider.py`). Tests pass
  (27/27). They are load-bearing for the verify loop ⇒ **commit them first**.
- **Config precedence**: explicit init args > env vars (`ASSISTANT_*`, `__`
  nesting) > config.yaml. A TUI persist to config.yaml is *lower* precedence
  than a `.env` `ASSISTANT_*` entry ⇒ on persist, drop the matching env
  override (existing pattern) so the pick isn't silently shadowed.
- **`_post` in the Zen provider has a malformed-response gap**:
  `raise_for_status()` then `resp.json()` then unguarded
  `data["choices"][0]["message"]`. A transient 200 with `{"choices": []}` or
  truncated JSON raises `KeyError`/`IndexError`/`JSONDecodeError` that escapes
  as a generic exception → triggers fallback on something that may have been a
  transient retry. No retry/backoff exists anywhere in `llm/`.
- **Zen's `/v1/models` endpoint works** — the provider's own `health()` already
  uses it. So listing Zen models from the TUI is feasible.

---

## 1. Stability branch — provider guards + retry

Scope: `assistant/llm/opencode_zen_provider.py`, `assistant/core/config.py`,
`default-config.yaml`, `config.yaml`.

### 1a. Guard `_post` against malformed responses
Add a small exception type and a guarded body. On a 200 whose body is unusable
(empty `choices`, missing `message`, non-JSON), raise a clean
`LLMResponseError(retryable=True)` instead of `KeyError`/`IndexError`. On 4xx
auth (401/403), the existing `raise_for_status()` raises
`httpx.HTTPStatusError`; mark those **non-retryable**. The verify loop
multiplies LLM call count, so this guard prevents a new failure class.

Approximate shape (the implementer fits this into `_post`):
```python
class LLMResponseError(Exception):
    def __init__(self, message: str, *, retryable: bool) -> None:
        super().__init__(message)
        self.retryable = retryable
```
- HTTP 429/5xx/transport errors → retryable.
- HTTP 401/403/400 → non-retryable (auth/config bug; retrying wastes time).
- Malformed 200 body → retryable (transient gateway hiccup).

### 1b. Minimal retry/backoff
2 retries, exponential backoff (0.5s, 1s, 2s) + jitter, on 429/503/transport
and retryable malformed bodies only. **Never** retry 4xx-auth. Lives in `_post`
(or a thin wrapper around it). Add a config field:

```python
# in LlmConfig
max_retries: int = 2  # retries on transient (429/5xx/transport) LLM failures
```
This is **config.yaml only — NOT surfaced in the TUI** (advanced).

### 1c. Commit the providers
As a focused commit *before* the verify work (they're load-bearing): the two
providers + two test files. Do not bundle the larger untracked blob (calendar,
AEC, stand-down, timer, persona, eval harness, etc.) — that's unrelated
in-flight work.

---

## 2. Config schema — `assistant/core/config.py`

### 2a. New `VerifyConfig` (top-level model)
Mirrors the `BargeInConfig`/`ConversationConfig` pattern (master toggle +
sub-toggles + a prompt-shaped subsystem). **Knobs only — the prompt is a
hard-coded constant in `verify.py` (§3), not a config field**, because the
prompt encodes the judgment/feedback safety structure that must not be
user-editable.

```python
class VerifyConfig(BaseModel):
    enabled: bool = True        # master kill switch; off = today's behavior
    pre: bool = True             # pre-tool gate: review pick+args before skill runs
    post: bool = True            # post-tool check: review answer before speech
    max_verify_rounds: int = 2   # per-stage sub-cap (rejects) within max_tool_rounds
    spoken_feedback: bool = True  # speak "let me double check" fillers on reject
```
Add `verify: VerifyConfig = VerifyConfig()` to `Config`.

### 2b. Raised defaults
```python
# RecorderConfig
max_ms: int = 30000          # was 10000 — allow long multi-clause utterances
# AgentConfig
turn_timeout_s: float = 45.0  # was 20.0 — fit the verify loop + one reject re-loop
```
`max_tool_rounds` stays 3. `start_timeout_ms` stays 5000 (unchanged — different
concern). `agent.max_tool_rounds` is **not surfaced in the TUI** (config.yaml
only).

### 2c. `llm.max_retries` (from §1b)
```python
# LlmConfig
max_retries: int = 2
```

### 2d. Reflect all of the above in `default-config.yaml` and `config.yaml`
Add a `verify:` block and the new `llm.max_retries` line. Update
`recorder.max_ms` and `agent.turn_timeout_s` defaults. Keep `env.example` in
sync (document the new `ASSISTANT_VERIFY__*`, `ASSISTANT_RECORDER__MAX_MS`,
`ASSISTANT_AGENT__TURN_TIMEOUT_S`, `ASSISTANT_LLM__MAX_RETRIES` vars).

---

## 3. Verify module — new `assistant/core/verify.py`

The home for the verify subsystem. Co-locates the prompt, the `Verdict`
dataclass, the `verify()` function, and round logic. Keeps `orchestrator.py`
the loop driver, not a verifier.

### 3a. Hard-coded prompt constant
A stage-aware prompt with one parametrized section. It names the three
verdicts inline (like `web_search._ASSESS_PROMPT` names its two shapes). The
**structural safety rule**: the `decision` (approve/rewrite/reject) is
produced persona-free; the spoken outputs (`feedback`, `rewritten_speech`)
may carry persona. The prompt instructs the model to decide first, then
produce spoken content. **One prompt constant** with a `{stage-specific
rewrite description}` block filled from a `stage` enum.

### 3b. `Verdict` dataclass (single, stage-aware, optional per-stage fields)
```python
@dataclass
class Verdict:
    decision: str            # "approve" | "rewrite" | "reject"
    feedback: str = ""      # spoken filler, persona-flavored (spoken on reject)
    rewritten_tool: str = ""        # pre-stage rewrite: replacement tool name
    rewritten_arguments: dict = field(default_factory=dict)  # pre-stage rewrite args
    rewritten_speech: str = ""       # post-stage rewrite: replacement answer, persona-flavored
```
Fields unused by a stage stay empty. This mirrors `ChatResponse` (holds
either `content` or `tool_calls`); the call site unpacks stage-aware.

### 3c. `verify()` function
```python
Stage = Literal["pre", "post"]

async def verify(
    stage: Stage,
    context: dict,            # request, history, picked tool, args, (post) result, (post) draft speech
    *,
    llm: LLMProvider,
    persona_suffix: str,      # persona on spoken outputs only
) -> Verdict | None:
    ...
```
- Calls `llm.complete(prompt, json=True, label="verify")`.
- `json.loads(raw)`; on any parse failure / non-dict / missing `decision` →
  **return `None`**. **Fail-open**: the caller treats `None` as `approve`
  (never block the turn on a broken verify).
- Builds the prompt with persona folded into the spoken-output instructions
  only (`feedback`, `rewritten_speech`); `decision`/`rewritten_tool`/
  `rewritten_arguments` instructions stay persona-free.

### 3d. Persona handling (the deliberate contract relaxation)
The verify call is the one "assess" call that *does* see persona — but only on
**spoken outputs**. Rationale (accepted trade): the only way to get
*zero-extra-latency* **and** *situational* feedback is to ride the call we're
already making; a separate persona-restyle call (the strict-contract option)
was rejected to preserve latency. The judgment-integrity guarantee is kept
*by prompt structure*: the `decision` is produced persona-free; persona
permitted only on `feedback`/`rewritten_speech`. `rewritten_speech` arrives
persona-flavored ⇒ **no separate restyle call on rewrites** (consistent rule:
*spoken outputs carry voice, routing/judgment don't*). This is opt-in via
`verify.spoken_feedback` (off → the call omits the `feedback` field).

---

## 4. Orchestrator — `assistant/core/orchestrator.py`

### 4a. New `on_say` callback (mid-turn speech channel)
```python
async def handle(
    self, text: str, history: list[Turn], *, spoken: bool,
    on_say: Callable[[str], Awaitable[bool]] | None = None,
) -> tuple[SkillResult | None, Skill | None]:
```
- The pipeline passes `on_say=self._speak` at its two `handle()` call sites
  (pipeline.py:538 and the text-injection path). Existing call sites that don't
  pass it (`_dispatch_reply`, etc.) get `None` and behave as today.
- `on_say=None` is the safe default: when `verify.enabled` is off or
  `verify.spoken_feedback` is off, the orchestrator never calls it. **No
  config-inconsistency guard** (if `on_say` is wired but feedback is off, it's
  simply never called).
- The orchestrator calls `barged = await on_say(filler)` and **aborts the
  turn** (`return`) if `barged` is True (a user who barges during "let me
  double check" wants the mic back now).

### 4b. Loop structure (the verified turn)
```
decide (chat_tools, persona-free)
  → [if verify.pre]  pre-verify(stage="pre", context={request, history, tool, args})
        • approve → proceed to skill
        • rewrite → replace pick/args with rewritten_tool/rewritten_arguments → proceed
        • reject  → if spoken_feedback: await on_say(feedback) [abort if barged]
                    → re-decide (consumes a max_tool_rounds iteration; counts toward
                      the per-stage max_verify_rounds sub-cap)
  → skill.handle() (executes; may have side effects — accepted trade: a wrong
                    mutating pick caught post-hoc by post-verify, not undone)
  → [if verify.post] post-verify(stage="post", context={request, history, tool, args, result, draft_speech})
        • approve → speak skill speech (→ existing persona path: tool answers self-persona;
                    direct answers restyle)
        • rewrite → speak rewritten_speech (persona-flavored by verify; NO restyle)
        • reject  → if spoken_feedback: await on_say(feedfer) [abort if barged]
                    → re-decide (consumes a max_tool_rounds iteration; per-stage sub-cap)
  → on TimeoutError: speak best_draft if it exists, else today's general fallback
```

### 4c. Counter interactions (the deliberately split guards)
- **Verify-rejects consume `max_tool_rounds` iterations** (tight 3-decide
  total — this is what makes the 45s budget sufficient).
- **A verify-rejected same-tool re-pick does NOT increment
  `_TOOL_REPEAT_CAP`.** That guard stays for *unguided model stalls* (the model
  re-calling the same tool with no new info). A verify-reject is an external
  signal justifying a corrected retry — different failure mode, different
  counter. Implement by tracking verify-rejected re-picks separately and not
  incrementing `tool_counts` for them.
- **`max_verify_rounds` is a per-stage sub-cap** within the 3-decide total:
  count rejects per stage; when a stage exceeds `max_verify_rounds`, stop
  calling verify for that stage (proceed with the current pick/answer rather
  than re-looping). So worst case is bounded by `max_tool_rounds=3`, not by a
  parallel verify budget.

### 4d. Filler timing (speak only on `reject`)
`on_say` fires **only when a verify stage returns `reject`** (both pre and
post), speaking that call's `feedback` string *before* the re-decide. Approve
and rewrite stay **silent**. Rationale: the filler truthfully narrates a
re-check ("let me double check that", "that's not right"); approve/rewrite
don't begin a new round, so a filler there would be a lie and would pad
happy-path latency. Matches the `web_search._say_soon` precedent (speaks at
the start of a *new search round*).

### 4e. Timeout-exhaustion (best-so-far, not discard)
Track `best_draft: str | None` through the loop:
- Set when the skill produces `result.speech`.
- Updated on each post-verify `rewrite` (to `rewritten_speech`) and `approve`
  (to the current draft).
On `TimeoutError`: if `best_draft` exists, **speak it** (return a
`SkillResult(speech=best_draft)`); else fall back to today's
`_fall_back_turn(draft=None)` → general. Rationale: the verify loop produces a
good draft before speaking; discarding it on timeout to re-derive from scratch
is the worst outcome (slow + loses validated work). A draft that passed
post-verify is verified-by-construction; a draft that only passed pre-verify
is the skill's own output — **no worse than today's unverified output**. So
this is strictly an improvement: equal on the empty case, strictly better when
a draft exists.

### 4f. Wiring in app.py
Pass `verify` config + `persona_suffix` into `Orchestrator.__init__`; pass
`on_say=self._speak` at the pipeline's `handle()` call sites. The orchestrator
constructs the verify context dicts and calls `verify.verify(...)`.

---

## 5. TUI discovery — `tui/discovery.py`

### 5a. `zen_health(base_url, api_key, **_) -> bool`
Mirrors `ollama_health`. GET `{base_url}/models` with `Authorization: Bearer
{api_key}`, short timeout. True on 2xx. Debug-level on failure (polled often).

### 5b. `zen_model_options(base_url, api_key, **_) -> list[tuple[str, str]]`
GET `{base_url}/models` → list of `(id, id)` pairs (Zen `/v1/models` returns
only ids — no sizes/params). On any error, return `[]` (the picker prepends
the current value so it's never empty).

### 5c. Widen `_select_options` threading (app.py)
Options providers already take `(host=..., **_)`. Thread `provider`,
`base_url`, `api_key` through the same `**_` (backward-compatible). The
`llm.model` provider switches on `provider`: Ollama →
`ollama_model_options(host)`; Zen → `zen_model_options(base_url, api_key)`.
The `llm.fallback_model` provider switches on `llm.fallback` (the *fallback*
provider's identity, not the primary's) — note this reuses the single shared
`host`/`base_url`/`api_key` (there are no separate fallback connection params).

### 5d. Detail panel
`#model-detail` stays Ollama-rich (sizes/params/quant). For Zen, show a
placeholder ("server-side model · details unavailable") since `/v1/models`
returns only ids. Do not call Ollama `/api/show` when provider is Zen.

---

## 6. TUI config fields — `tui/config_schema.py`

Append to `FIELDS` (auto-renders; no new widget code for these kinds):

```python
# Verify + turn bounds (the five surfaced knobs)
Field(("verify", "enabled"), "Verify master", "toggle"),
Field(("verify", "spoken_feedback"), "Verify feedback", "toggle"),
Field(("verify", "max_verify_rounds"), "Verify rounds", "number", lo=0, hi=4, step=1),
Field(("recorder", "max_ms"), "Max utterance (ms)", "number", lo=5000, hi=60000, step=1000),
Field(("agent", "turn_timeout_s"), "Turn budget (s)", "number", lo=10, hi=120, step=5),
```
**Not surfaced** (config.yaml only): `verify.pre`, `verify.post`,
`agent.max_tool_rounds`, `llm.max_retries`. These are advanced/debugging knobs.

### LLM-identity fields (provider-aware)
```python
Field(("llm", "provider"), "LLM provider", "select", discovery.llm_provider_options),
Field(("llm", "model"), "LLM model", "select", discovery.llm_model_options),
Field(("llm", "fallback"), "Fallback provider", "select", discovery.llm_fallback_options),
Field(("llm", "fallback_model"), "Fallback model", "select", discovery.llm_fallback_model_options),
```
- `llm_provider_options` / `llm_fallback_options`: static lists
  (`["ollama", "opencode-zen"]`; fallback also offers `""` = none). Like
  `log_levels`.
- `llm_model_options` / `llm_fallback_model_options`: provider-aware (§5c).
  The fallback-model provider binds to `llm.fallback`'s provider, not the
  primary's.

### Pick behavior (persist + restart)
All four LLM-identity picks **persist to config.yaml and restart** (match the
existing `_on_model_picked`/`_on_voice_picked` precedent), **dropping the
matching `ASSISTANT_LLM__*` env override** on persist so a `.env` entry doesn't
shadow the new default. Extend `_open_picker`'s `_picked` callback in
`tui/screens/config.py` to handle these four keys (persist + restart, drop
override). **Accepted minor wart**: picking `fallback` then `fallback_model`
restarts twice (two picks, two restarts) — rare setup action, not worth
batching machinery.

---

## 7. TUI app — `tui/app.py`

### 7a. Tiered LLM health (one dot, fallback-aware)
Replace `_check_ollama_health` with `_check_llm_health`:
- Probe **primary** (Zen → `zen_health(base_url, api_key)`; Ollama →
  `ollama_health(host)`) and, **if a fallback is configured**, probe the
  fallback too.
- Derive `_llm_tier` ∈ `{up, degraded, down}`: up = both ok; degraded = one
  down (primary down + fallback up, or primary up + fallback down); down =
  all down.
- The status line and the NavBar dot reflect the tier (green / yellow / red)
  and are **provider-aware in text** (e.g. "zen ✓ · ollama ✓" / "zen ✗ · ollama
  ✓ (degraded)"). Today's hardcoded "ollama up/DOWN" is a lie when Zen is
  primary — this fixes it. Semantics match `FallbackLLMProvider.health()`
  (`primary_ok or fallback_ok`).

### 7b. "Restart LLM" button — conditional
The button's meaning is "restart the local Ollama server". It only makes sense
when Ollama is **in the chain** (primary *or* fallback). When `provider=zen`
and `fallback=ollama`, the button restarts the *fallback* server (still useful
— it's the safety net). When there's no Ollama in the chain at all (Zen
primary, no fallback), **hide the button**. Gate on "is Ollama in the chain".

### 7c. Startup gating
`_ensure_ollama` (auto-start Ollama at launch) is gated on "is Ollama actually
in use" (primary or fallback). When Zen is primary with no Ollama fallback,
don't spawn an unused `ollama serve` at startup.

### 7d. Ollama log channel
Keep the existing "ollama" log channel and `RunLogWriter` for the spawned
Ollama server's output. It's still useful when Ollama is the fallback. No
change needed beyond the gating in 7b/7c.

---

## 8. Tests

Existing (green, 27/27): `tests/test_zen_provider.py`,
`tests/test_fallback_provider.py`. New:

- **`tests/test_verify.py`**: `Verdict` parsing for approve/rewrite/reject at
  each stage; stage-specific field extraction; `None` on malformed/missing
  `decision` (fail-open); persona only on spoken outputs (prompt-construction
  test if feasible).
- **Orchestrator verify-loop tests** (extend or new file): filler speaks only
  on `reject` (pre and post); `on_say` barge aborts the turn; `best_draft`
  spoken on `TimeoutError`, else general fallback; verify-reject consumes a
  `max_tool_rounds` iteration; verify-rejected same-tool re-pick does *not*
  increment `_TOOL_REPEAT_CAP`; per-stage `max_verify_rounds` sub-cap stops
  re-looping; `verify.enabled=false` ⇒ byte-identical to today's behavior;
  `on_say=None` ⇒ no fillers, no crash.
- **Provider guard tests**: malformed 200 (`{"choices": []}`, truncated JSON)
  → `LLMResponseError(retryable=True)`; retry on 429/503/transport; no retry
  on 401/403; `max_retries` honored.
- **TUI discovery tests**: `zen_health`/`zen_model_options` via
  `httpx.MockTransport`; provider-aware options routing.
- **Config tests**: `VerifyConfig` defaults; raised `max_ms`/`turn_timeout_s`
  defaults; env override precedence for the new vars.

Conventions: `pytest-asyncio` `auto` mode (no markers). Tests never touch real
models/devices (stubbed). Bare `except Exception` in pipeline/orchestrator is
intentional (don't "fix" it).

---

## 9. Phases (implementation order)

1. **Commit providers** (§1c) — focused commit of the two providers + tests.
2. **Provider guards + retry** (§1a, §1b) — `_post` guard, `LLMResponseError`,
   minimal backoff, `llm.max_retries` config field + tests.
3. **Config schema** (§2) — `VerifyConfig`, raised defaults, `max_retries`,
   update `default-config.yaml`/`config.yaml`/`env.example`.
4. **`verify.py` module** (§3) — prompt, `Verdict`, `verify()` + tests.
5. **Orchestrator** (§4) — `on_say` callback, verify loop, counter interactions,
   filler-on-reject, best-draft-on-timeout, app.py wiring + tests.
6. **TUI discovery** (§5) — `zen_health`, `zen_model_options`, provider-aware
   options threading + tests.
7. **TUI config fields** (§6) — the five verify/turn fields + four
   LLM-identity fields, persist+restart pick behavior.
8. **TUI app** (§7) — tiered health, conditional Restart button, startup
   gating.

Each phase is independently testable. Phases 1–2 are decoupled from 3–5; 6–8
build on 3. Phases 1–5 are the stability/quality branch; 6–8 are the TUI
branch; both share the config schema (3).

---

## 10. Explicitly out of scope (follow-ons)

- **Per-skill `dry_run`/preview** so post-verify can catch a wrong *mutating*
  pick before its side effect — accepted trade for now is side-effect-then-
  verify (a wrong reminder gets created, then the spoken answer corrects it).
- **Model-native thinking (B)** as the verify *runner* — the spine is the
  explicit verify call (A); a reasoning model can later *run* the verify step,
  not replace it.
- **Surfacing `llm.base_url`/`llm.api_key`** in the TUI — the key is a secret
  (shoulder-surfing on a touch screen, AGENTS.md "API key via env, never
  config.yaml"); base_url rarely changes. Stay in `.env`.
- **`.env`-shadows-the-pick reconciliation/warning** — on persist we drop the
  matching override (existing pattern); a TUI warning if `.env` would shadow a
  future pick is a separate UX nicety.
- **Narrating `rewrite` verdicts** — fillers speak only on `reject` (the
  truthful "re-check" narration). `rewrite` is a silent self-correction; if
  later desired, add `rewrite` to the trigger set (one-line change).
