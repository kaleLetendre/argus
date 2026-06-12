"""Shared data structures for the interaction-agents contract."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class Utterance:
    """A recognized user communication."""
    text: str
    source: str
    session_id: str
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @classmethod
    def from_text(cls, text: str, session_id: str, source: str = "keyboard") -> Utterance:
        return cls(text=text, source=source, session_id=session_id)


@dataclass
class Reply:
    """A response to an Utterance."""
    text: str
    kind: str  # "answer" | "error"
    found: bool = True
