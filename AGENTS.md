# hearth

An Alexa-like personal assistant. The walking skeleton is a console chat client
that sends text over WebSocket to a backend. The backend streams the text to one
LLM through an OpenAI-compatible API and streams the reply back.

## Layout

```
libs/protocol/  hearth-protocol -> import hearth.protocol (wire models)
apps/backend/   hearth-backend  -> import hearth.backend (server, LLM, history)
apps/chat/      hearth-chat     -> import hearth.chat (console client)
config/         example configs; the real YAML files are gitignored
```

`backend` and `chat` depend on `protocol`. `chat` never imports `backend`, and
`backend` never imports `chat`.

## Namespace packages

`src/hearth/` is a namespace package and must not contain an `__init__.py`.
Only `src/hearth/<name>/__init__.py` exists for each distribution. Do not add a
guard test for this.

## Commands

```
uv sync
uv run ruff check
uv run ruff format --check
uv run pyright
uv run pytest
```

## Secrets

LLM API keys live only in environment variables or `.env`. YAML names the
environment variable with `api_key_env`; it never holds the key. Device tokens
live in `config/chat.yaml` or `HEARTH_CHAT__TOKEN`, and `config/devices.yaml`
stores only their SHA-256 hashes. `config/backend.yaml`, `config/chat.yaml`,
`config/devices.yaml`, `.env`, and `data/` are gitignored.

## Run locally

```
cp config/backend.example.yaml config/backend.yaml
uv run hearth-backend add-device desk
cp config/chat.example.yaml config/chat.yaml   # put the printed token in token:
uv run hearth-backend serve
uv run hearth-chat                              # in another terminal
```

Point `roles.fast` at a local Ollama model (`gemma4:e2b` by default) or another
OpenAI-compatible provider. `slow` is configured but unused by the skeleton.
