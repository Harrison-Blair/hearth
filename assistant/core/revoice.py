"""Revoicer: restyle an already-decided plain reply in the persona's voice.

Sits at the pipeline's ``_speak`` choke point (`core/pipeline.py`) for skill
replies that are not already persona-flavored (`SkillResult.voiced=False`). Every
safety net lives here:

- A failure-cooldown circuit: any failure (error, timeout, empty output, a digit
  mismatch) opens the circuit for ``cooldown_s``, so a flaky LLM doesn't add
  latency to every subsequent reply.
- A bounded timeout (``timeout_s``) via ``asyncio.wait_for``.
- A digit-preservation guard: every digit sequence in the plain text must appear
  verbatim in the styled output, or the styled output is discarded.

``enabled=False`` (persona off, or ``revoice_enabled`` off) is a pure passthrough:
no LLM call, no added latency.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Callable

from assistant.llm.base import LLMProvider

log = logging.getLogger(__name__)

_RESTYLE_INSTRUCTION = (
    "Restyle this exact reply in your voice; do not answer, add, or remove "
    "information; keep every time, date, and number byte-exact."
)

_DIGITS_RE = re.compile(r"\d+")

# Cooldown after a revoice failure before the circuit allows another live call.
_DEFAULT_COOLDOWN_S = 30.0


class Revoicer:
    def __init__(
        self,
        llm: LLMProvider,
        persona_segment: str,
        *,
        enabled: bool = True,
        timeout_s: float = 5.0,
        cooldown_s: float = _DEFAULT_COOLDOWN_S,
        healthy: bool = True,
        now: Callable[[], float] = time.monotonic,
    ) -> None:
        self._llm = llm
        self._system = f"{persona_segment}\n\n{_RESTYLE_INSTRUCTION}"
        self._enabled = enabled
        self._timeout = timeout_s
        self._cooldown = cooldown_s
        self._now = now
        # A future timestamp before which the circuit is open (passthrough only).
        # Seeded unhealthy at boot behaves exactly like a fresh failure.
        self._open_until = self._now() + cooldown_s if not healthy else 0.0

    async def revoice(self, text: str) -> str:
        """Restyle ``text`` in persona, or return it unchanged on any failure,
        timeout, digit mismatch, or while the circuit is open."""
        if not self._enabled or self._now() < self._open_until:
            return text
        try:
            styled = await asyncio.wait_for(
                self._llm.complete(text, system=self._system, label="revoice"),
                timeout=self._timeout,
            )
        except Exception as exc:  # noqa: BLE001 - any failure falls back to plain text
            log.warning("Revoice failed: %s", exc)
            self._open_circuit()
            return text
        styled = styled.strip() if styled else ""
        if not styled:
            log.warning("Revoice returned empty output; speaking the plain reply")
            self._open_circuit()
            return text
        if not self._digits_preserved(text, styled):
            log.warning("Revoice output dropped or mutated a digit; speaking the plain reply")
            self._open_circuit()
            return text
        return styled

    def _open_circuit(self) -> None:
        self._open_until = self._now() + self._cooldown

    @staticmethod
    def _digits_preserved(original: str, styled: str) -> bool:
        return all(d in styled for d in _DIGITS_RE.findall(original))
