"""Persona restyle stage: runs at the loop tail on the final answer only."""
from __future__ import annotations


async def restyle(text: str, ctx=None) -> str:
    """No-op: returns `text` unchanged. FTHR-011 gives this a real revoice."""
    return text
