# FTHR-012 molt evidence: openrouter/free config example + compatibility test

## AC-1

Tests: `tests/test_openrouter_compat.py` (new file, 4 tests).

**Pre-implementation (failing for the expected reason — the test file did not
exist yet):**

```
$ mv tests/test_openrouter_compat.py /tmp/test_openrouter_compat.py.bak
$ pytest tests/test_openrouter_compat.py -v
============================= test session starts ==============================
platform linux -- Python 3.12.13, pytest-9.1.1, pluggy-1.6.0 -- .../.venv/bin/python3.12
...
collecting ... ERROR: file or directory not found: tests/test_openrouter_compat.py

collected 0 items

============================ no tests ran in 0.00s =============================
$ mv /tmp/test_openrouter_compat.py.bak tests/test_openrouter_compat.py
```

Note per spec: `OpenAICompatibleProvider` and the `GATEWAYS` table already shipped
in FTHR-010, so once the test file exists it asserts a contract the generic
provider already satisfies (no new provider code path needed — that's the point
of the test: `openrouter/free` needs no special-casing). The genuine
pre-implementation failure is therefore the test file's absence (collection
error above), not a provider-code failure.

**Post-implementation (passing):**

```
$ pytest tests/test_openrouter_compat.py -v
============================= test session starts ==============================
platform linux -- Python 3.12.13, pytest-9.1.1, pluggy-1.6.0 -- .../.venv/bin/python3.12
...
collecting ... collected 4 items

tests/test_openrouter_compat.py::test_complete_sends_openrouter_free_model_verbatim PASSED [ 25%]
tests/test_openrouter_compat.py::test_chat_sends_openrouter_free_model_verbatim PASSED [ 50%]
tests/test_openrouter_compat.py::test_chat_tools_sends_model_and_tools PASSED [ 75%]
tests/test_openrouter_compat.py::test_complete_json_sets_response_format PASSED [100%]

============================== 4 passed in 0.06s ===============================
```

## AC-2

`tests/test_openrouter_compat.py` builds
`OpenAICompatibleProvider(model="openrouter/free", api_key="k",
base_url=GATEWAYS["openrouter"]["base_url"])` over an `httpx.MockTransport` and
asserts, per call, on the exact JSON body the provider sends — no branch in
`assistant/llm/openai_compatible_provider.py` special-cases the
`openrouter/free` id; the same generic `complete`/`chat`/`chat_tools` code paths
used for every other model id serialize it verbatim:

- `test_complete_sends_openrouter_free_model_verbatim`: `body["model"] ==
  "openrouter/free"` on `POST /chat/completions` via `complete()`.
- `test_chat_sends_openrouter_free_model_verbatim`: same assertion via `chat()`.
- `test_chat_tools_sends_model_and_tools`: `body["model"] == "openrouter/free"`
  and `body["tools"] == tools` via `chat_tools(tools=...)`.
- `test_complete_json_sets_response_format`: `body["model"] ==
  "openrouter/free"` and `body["response_format"] == {"type": "json_object"}`
  via `complete(json=True)`.

All four pass (see AC-1 post-implementation run above).

## AC-3

`default-config.yaml` (`llm:` block):
- `provider` comment extended to `# ollama | opencode-zen | openrouter`.
- `base_url: ""` (was a hardcoded Zen URL) with a comment explaining blank uses
  the selected provider's default from the `GATEWAYS` table in
  `assistant/llm/openai_compatible_provider.py`; the active `provider: "ollama"`
  doesn't use `base_url` at all, so this is a safe default-only change.
- A new commented block: `provider: "openrouter"`, `model: "openrouter/free"`,
  `api_key: ""` (env-var comment, no key), `fallback: "ollama"`, plus the two
  caveats from the spec (key still required; free models rate-limit/rotate).

`config.yaml`: same commented `openrouter/free` example appended beside the
active `llm:` block. Active values (`provider: opencode-zen`, `model:
gemma4:12b`, `base_url: https://opencode.ai/zen/v1`, etc.) are byte-for-byte
unchanged — verified below.

```
$ git diff config.yaml
diff --git a/config.yaml b/config.yaml
index c055618..ab14ed1 100644
--- a/config.yaml
+++ b/config.yaml
@@ -52,6 +52,15 @@ llm:
   fallback: ollama
   fallback_model: qwen3:14b
   max_retries: 2
+  # OpenRouter's free router (provider: "openrouter", model: "openrouter/free")
+  # filters to a capable model at $0 cost among currently-free models. Caveats: an
+  # API key is still required (OpenRouter has no anonymous tier); free models are
+  # rate-limited and rotate over time, so availability isn't guaranteed.
+  # llm:
+  #   provider: "openrouter"
+  #   model: "openrouter/free"
+  #   api_key: ""           # set via ASSISTANT_LLM__API_KEY, not here
+  #   fallback: "ollama"
 persona:
   enabled: true
   strength: terse
```

No existing key in `config.yaml`'s active `llm` block changed — only additive
commented lines appended after `max_retries: 2`.

```
$ python -c "
import yaml
d = yaml.safe_load(open('config.yaml'))
print(d['llm'])
d2 = yaml.safe_load(open('default-config.yaml'))
print(d2['llm'])
"
{'provider': 'opencode-zen', 'model': 'gemma4:12b', 'host': 'http://localhost:11434', 'timeout': 60.0, 'health_timeout': 5.0, 'num_ctx': 8192, 'think': False, 'serve_cmd': ['ollama', 'serve'], 'api_key': '', 'base_url': 'https://opencode.ai/zen/v1', 'fallback': 'ollama', 'fallback_model': 'qwen3:14b', 'max_retries': 2}
{'provider': 'ollama', 'model': 'qwen2.5:3b-instruct', 'host': 'http://localhost:11434', 'timeout': 60.0, 'health_timeout': 5.0, 'num_ctx': 8192, 'think': False, 'serve_cmd': ['ollama', 'serve'], 'api_key': '', 'base_url': '', 'fallback': '', 'fallback_model': '', 'max_retries': 2}
```

`config.yaml`'s active `llm` block is unchanged except the intentional
`default-config.yaml` `base_url` blanking (spec-required); no other test in the
repo asserted `default-config.yaml`'s `base_url` value (checked via
`grep -rn "base_url" tests/`), so nothing else needed updating.

No API key appears in either file:

```
$ grep -n "api_key" config.yaml default-config.yaml
config.yaml:50:  api_key: ''
config.yaml:62:  #   api_key: ""           # set via ASSISTANT_LLM__API_KEY, not here
default-config.yaml:63:  api_key: ""             # set via env var, not here
default-config.yaml:80:  #   api_key: ""           # set via ASSISTANT_LLM__API_KEY, not here
```

All blank/comment placeholders — no real key.

## AC-4

```
$ ruff check assistant tests
All checks passed!

$ pytest
...
================== 858 passed, 2 skipped, 1 warning in 22.71s ==================
```

No network access used anywhere (all HTTP calls in the new test go through
`httpx.MockTransport`).
