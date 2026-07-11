---
id: FTHR-008
title: Typed BrainError crash-hardening
plumage: PLM-002
status: pipping
priority: P1
depends_on: []
authored: 2026-07-11T02:45:14Z
agent: fledge-orchestrate/planning
fledge_version: 0.3.4
---

# FTHR-008: Typed BrainError crash-hardening

## Description
The three raw-exception exit points inside `_OpenAICompatBackend.complete()` (`hearth/brain/openai_compat.py`) currently let `httpx.HTTPStatusError`, transport errors, `KeyError`/malformed-body errors, and `json.JSONDecodeError` propagate uncaught out of the brain layer. This feather introduces a typed `BrainError` exception (client-safe `reason` + internal `detail`) and wraps those three raise sources so callers get a single, curated exception type instead of a grab-bag of library exceptions. This is foundational, topology-independent hardening that FTHR-009 and FTHR-012 both build on (turning `BrainError` into a graceful consult observation, and a curated client-facing message, respectively).

## Affected Modules
- New `hearth/brain/errors.py` — `BrainError(reason: str, detail: str)`, an `Exception` subclass. `reason` is short and client-safe (e.g. "backend unreachable", "unreadable response"); `detail` carries internal diagnostic context (status code, raw body snippet) and is never shown to the client.
- `hearth/brain/openai_compat.py:80-95` (`_OpenAICompatBackend.complete`) — wrap the three raise sources:
  - `response.raise_for_status()` (`:83`) and the underlying `await self._client.post(...)` (`:80-82`) transport failures → catch `httpx.HTTPStatusError` and `httpx.HTTPError`, raise `BrainError("backend unreachable", detail=<status/exception text>)`.
  - `body["choices"][0]` / `choice["message"]` (`:85-86`) — catch `KeyError`/`IndexError` from a malformed body, raise `BrainError("unreadable response", detail=<body repr, truncated>)`.
  - `json.loads(tc["function"]["arguments"])` (`:92`) — catch `json.JSONDecodeError`, raise `BrainError("unreadable response", detail=<raw arguments string>)`.
- New `tests/test_brain_errors.py`.
- Existing `tests/test_local_backend.py`, `tests/test_remote_backend.py` (success-path regression only — no rework expected).

## Approach
- `BrainError` is a plain `Exception` subclass, two fields, no external dependencies — no need for an error-code enum or hierarchy (single error family is enough for this feather; FTHR-012 curates further at the veneer boundary).
- Wrap `complete()`'s three risk zones in narrow `try/except` blocks at their exact call sites (not one blanket `try` around the whole method) so each failure mode maps to a distinct, accurate `reason`.
- `.detail` must never include the `Authorization` header or the resolved API key — build detail strings from the response status/body or exception message only, never from `headers` or `self._config`.
- Keep the success path (no exception) byte-for-byte unchanged — existing `test_local_backend.py`/`test_remote_backend.py` happy-path assertions must keep passing untouched.

## Tests
Written test-first in `tests/test_brain_errors.py` (new), using the existing `httpx.MockTransport` pattern from `test_local_backend.py`/`test_remote_backend.py`:
- `test_http_error_raises_brain_error` — MockTransport returns HTTP 500; `complete()` raises `BrainError` (not `httpx.HTTPStatusError`); `.reason` is the curated backend-unreachable string; `.detail` contains the status code.
- `test_malformed_body_raises_brain_error` — MockTransport returns 200 with a body missing `choices`; `complete()` raises `BrainError` with the unreadable-response reason.
- `test_bad_tool_arguments_raises_brain_error` — MockTransport returns a tool_call whose `arguments` is not valid JSON; `complete()` raises `BrainError`, not `json.JSONDecodeError`.
- `test_brain_error_never_leaks_api_key` — construct a backend with a resolvable API key/Authorization header, force a `BrainError` via any of the above, and assert the key/header value appears in neither `.reason` nor `.detail`.
- Run existing `tests/test_local_backend.py` and `tests/test_remote_backend.py` unmodified to confirm the success path is untouched (regression, not new tests).

Implementation order: write `test_brain_errors.py` first, run against unmodified `openai_compat.py`, capture the failures (import error / uncaught exceptions, not `BrainError`), then implement `errors.py` + the three wraps until green.

## Acceptance Criteria
- [ ] AC-1: The tests listed above were observed failing before implementation (capturing the uncaught `httpx`/`KeyError`/`json.JSONDecodeError` as the failure reason) and pass after.
- [ ] AC-2: An HTTP 500 (or transport failure) from `complete()` raises `BrainError`, not `httpx.HTTPStatusError`; `.reason` is a curated "backend unreachable"-style string; `.detail` contains the status code/exception text.
- [ ] AC-3: A malformed response body (missing `choices`) raises `BrainError` with an "unreadable response" reason, not a raw `KeyError`/`IndexError`.
- [ ] AC-4: A tool-call with non-JSON `arguments` raises `BrainError`, not a raw `json.JSONDecodeError`.
- [ ] AC-5: Neither `.reason` nor `.detail` on any raised `BrainError` ever contains the API key or `Authorization` header value; `tests/test_local_backend.py` and `tests/test_remote_backend.py` still pass unmodified (success path unchanged).
