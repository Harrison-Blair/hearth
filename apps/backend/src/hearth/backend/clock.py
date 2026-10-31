"""Shared clock helpers."""

from datetime import UTC, datetime


def utc_now() -> datetime:
    """Return the current time as an aware UTC datetime."""
    return datetime.now(UTC)
