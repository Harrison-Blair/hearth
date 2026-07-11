"""Typed exception for the brain layer.

Curates the grab-bag of httpx/KeyError/json exceptions that `_OpenAICompatBackend.complete()`
can raise into a single exception type with a client-safe `reason` and an internal `detail`.
"""
from __future__ import annotations


class BrainError(Exception):
    """A brain backend failure.

    `reason` is short and safe to show to a client. `detail` carries internal diagnostic
    context (status code, raw body snippet) and must never include the Authorization
    header or resolved API key.
    """

    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(reason)
        self.reason = reason
        self.detail = detail
