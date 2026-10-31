"""Redact configured API keys from text before it is persisted or displayed."""

from __future__ import annotations

from collections.abc import Iterable

REDACTED = "[REDACTED]"


class Redactor:
    """Replace configured secret values in arbitrary text."""

    def __init__(self, secrets: Iterable[str]) -> None:
        self._secrets = tuple(
            sorted({secret for secret in secrets if secret}, key=len, reverse=True)
        )

    def redact(self, text: str) -> str:
        """Return ``text`` with every configured secret replaced."""
        for secret in self._secrets:
            text = text.replace(secret, REDACTED)
        return text
