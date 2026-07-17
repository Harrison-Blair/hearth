# Manual smoke procedure: hearth spine (veneer + loop + router + tools)

This is a **manual** check, not a gating automated test (the automated,
hermetic proof lives in `tests/test_e2e_veneer.py`). It exists because this
Phase 0 development environment has no access to a live Ollama server, a live
OpenRouter API key, or the live Wikipedia API — someone with those available
needs to run this by hand before trusting the spine against real services.

Run these from the repo root, with the runtime venv active:

```bash
python3 -m venv .venv && .venv/bin/pip install -e '.[all]'
source .venv/bin/activate
```

## 1. Local-only smoke test (Ollama)

1. Install and start Ollama, then pull the configured model:
   ```bash
   curl -s http://127.0.0.1:11434 >/dev/null || ollama serve &
   ollama pull qwen3:14b
   ```
   (If Ollama is already running as a system/user service, the `curl` check
   skips the manual `serve` — running a second instance fails with
   `bind: address already in use`.)
2. Edit `config.yaml` so the tool tier can't reach out anywhere: set
   `llm.tiers.tool: local` (or `llm.backends.remote.enabled: false` — either
   forces the tool-use turn to resolve to the local backend).
3. Start the daemon in one terminal:
   ```bash
   hearth run
   ```
4. In a second terminal, run the chat veneer and drive it interactively:
   ```bash
   hearth-chat
   ```
5. Type a plain question, e.g. `what's 2 plus 2`, press enter. Expect a
   sensible spoken-style answer printed back, no `error:` line, no crash in
   either terminal.
6. Type a question that should trigger the Wikipedia tool, e.g.
   `who was Ada Lovelace`. Expect to see a `…search` line (the `tool_activity`
   start/end markers rendered by the client) followed by a sensible answer
   that reflects real Wikipedia content, no crash.

## 2. Remote-tier smoke test (OpenRouter)

1. Add your OpenRouter key to `.env`:
   ```
   HEARTH_LLM__OPENROUTER_API_KEY=sk-...
   ```
2. Set `config.yaml` so the tool tier routes to the remote backend:
   `llm.tiers.tool: remote` and `llm.backends.remote.enabled: true` (the
   checked-in `config.yaml` already defaults to this).
3. Restart the daemon (`hearth run`) so it picks up the new `.env`/config.
4. Repeat step 6 above (a Wikipedia-triggering question) through
   `hearth-chat`. Expect the same shape of response:
   `…search` activity, then a sensible answer.
5. Confirm the turn actually went to the remote tier by inspecting the event
   log:
   ```bash
   sqlite3 hearth.db "select payload_json from events where type='routing_decision' order by id desc limit 1;"
   ```
   Expect `"tier": "tool"` and `"backend_name": "remote"` in the JSON.

## 3. Chat veneer as an installed console script (FTHR-024 AC-4)

The automated suite runs in-process against imported modules; it never
exercises the `hearth-chat` entry point or the real terminal. This check does,
and must be run by hand after any change to the chat veneer or its packaging.

1. Reinstall so `[project.scripts]` regenerates the entry point:
   ```bash
   pip install -e .
   ```
2. Start the engine in one terminal: `hearth run`.
3. In a second terminal, run the **installed console script** (not `python -m`):
   ```bash
   hearth-chat
   ```
   Take a real turn (e.g. `what's 2 plus 2`) and confirm the `> ` prompt, the
   red `[hearth]` answer tag, and a sensible answer.
4. Stop the engine (Ctrl-C in the first terminal), then run `hearth-chat`
   again. Expect a single plain line naming the engine host/port and that it
   may not be running, a **non-zero** exit (`echo $?` → non-zero), and **no
   Python traceback**.

## 4. Telling environment issues from real bugs

- **No Ollama running / model not pulled**: the local-only test's plain
  question fails immediately, or `hearth run` logs a connection-refused /
  timeout error at startup or on first turn. Fix: start `ollama serve` and
  `ollama pull <model>`, then retry — this is not a spine bug.
- **No OpenRouter key set / invalid key**: the remote-tier test's turn comes
  back as an `error:` line on the client, and the daemon log shows a 401/403
  from the OpenRouter HTTP call. Fix: check `.env` has a valid
  `HEARTH_LLM__OPENROUTER_API_KEY` and that `.env` is actually being loaded
  (restart the daemon after editing it) — this is not a spine bug.
- **No network access to Wikipedia**: the tool-triggering question in either
  section returns an answer that says the search failed, or the `observation`
  event logged for that turn contains an `error: ...` string (check via the
  same `sqlite3` query as above with `type='observation'`) rather than a
  crash. This is an environment/network issue, not a spine bug.
- **A real bug** looks different from all of the above: the daemon crashes
  outright (traceback in the terminal running `hearth run`), the client
  hangs past `agent.turn_timeout_s` (45s) with no response, the wire messages
  don't follow the `tool_activity`(start)→`tool_activity`(end)→`answer`→`done`
  shape, or the event log is missing rows for a turn that clearly happened.
  Any of these point at the spine itself, not the environment, and should be
  filed as a bug rather than reattributed to missing credentials/services.
