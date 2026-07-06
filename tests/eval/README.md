# Tool-call eval

An opt-in regression harness that measures whether the **configured live Ollama
model** produces correctly-formatted tool calls through the real orchestrator
decision path — the reference doc's **Stage-1 gate (≥90% correct tool
formatting)**.

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
skill registry, tool schemas, system prompt), minus audio/TTS. The LLM-free
keyphrase fast path is **disabled** so every case exercises the model — that
shortcut is not what this eval measures. Skills are wired but never executed; only
the tool decision is scored.

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
