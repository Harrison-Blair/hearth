# Tool-call eval

Two harnesses share this directory:

- **Live eval** (`run_eval.py`) — opt-in, measures the *configured Ollama model*
  against `dataset.py`. Use it to compare models/prompts.
- **Replay eval** (`run_replay.py`) — offline, re-runs *captured real turns*
  through the real orchestrator with recorded LLM responses. Use it as a
  regression gate on orchestrator/routing code: refactors must reproduce
  identical decisions from identical model output.

## Replay: capture → curate → replay

```bash
# 1. Capture: run the daemon (Ollama up) and have a few real turns
python -m assistant.app          # speak or type turns, Ctrl-C when done

# 2. Extract the turn + LLM records from that run's JSONL log
python -m tests.eval.extract logs/assistant-<stamp>/assistant.jsonl \
    -o tests/eval/captures/session1.jsonl

# 3. Curate: open the capture, delete unwanted `turn` lines
#    (leftover llm.* lines are harmless unused cache entries)

# 4. Replay offline — no Ollama needed
python -m tests.eval.run_replay
pytest tests/eval/test_replay_eval.py -q   # same gate via pytest
```

`test_replay_eval.py` **skips** while `captures/` has no turn records, so a fresh
checkout stays green; once a baseline is committed the gate asserts 100%.

### Miss semantics

Replay responses are keyed on a content hash of the exact prompt/messages/tool
catalogue. Any deliberate change to the system prompt, tool schemas, or
registered skills makes captured keys miss (`ReplayMiss`) and the eval fail —
that is the signal to **re-record the baseline** (repeat capture → curate) after
reviewing that the new decisions are right. `fallback` turns (LLM was down at
capture time) are excluded from scoring.

## Live eval

Measures whether the **configured live Ollama model** produces correctly-formatted
tool calls through the real orchestrator decision path — the reference doc's
**Stage-1 gate (≥90% correct tool formatting)**.

## What it measures

For each utterance in `dataset.py` it runs the orchestrator's tool decision
(`Orchestrator._decide` — native Ollama tool-calling with the JSON fallback,
exactly as production routes) and scores:

- **tool-name correctness** — the model called the right skill intent (`time`,
  `timer`, `reminder`, `list_reminders`, `manage_reminders`, `weather`,
  `web_search`), or answered directly for general-knowledge cases; and
- **required-argument presence** — the key slot(s) are present and non-empty
  (e.g. a `duration` for a timer, a `query` for web search, a `location` for
  "weather in Tokyo"). Argument checks are loose on purpose: presence/plausibility,
  not exact strings, since the model has latitude in phrasing.

The aggregate score must be **≥ 0.90**.

The orchestrator is built exactly as `assistant/app.py` builds it (same LLM,
skill registry, tool schemas, system prompt), minus audio/TTS. Skills are wired
but never executed; only the tool decision is scored.

## How to run

```bash
source .venv/bin/activate

# via pytest (opt-in; skips when the gate is off or Ollama is down)
ASSISTANT_EVAL=1 pytest tests/eval/ -s

# or standalone, with a printed per-case table
ASSISTANT_EVAL=1 python -m tests.eval.run_eval
```

Point it at a different model/host with the usual config env vars, e.g.
`ASSISTANT_LLM__MODEL=gemma3:4b`.

## Opt-in / skip behaviour

The pytest test **skips** (never fails) when either:

- `ASSISTANT_EVAL` is not `1` (default), or
- Ollama is unreachable or the configured model isn't pulled
  (`OllamaProvider.health()`).

So a normal offline `pytest` run stays green.

## Scores are model-dependent

The number reflects the model you have configured — it will differ between, say,
`qwen3` today and a `gemma` variant later. Re-run after changing `llm.model` and
treat the printed table as the source of truth for which cases regressed.
