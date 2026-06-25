"""Plain data records passed along the voice pipeline.

Kept in core/ so interfaces in audio/stt/nlu/skills can share them without
importing each other (avoids circular dependencies).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class WakeEvent:
    """A wake-word activation."""

    name: str
    score: float


@dataclass
class Command:
    """A transcribed user utterance to be routed and handled."""

    text: str


@dataclass
class Intent:
    """A routed intent with extracted slots."""

    type: str
    slots: dict = field(default_factory=dict)
    raw_text: str = ""
    confidence: float = 1.0


@dataclass
class SkillResult:
    """The outcome of a skill handling a command."""

    speech: str
    data: dict | None = None
    success: bool = True
