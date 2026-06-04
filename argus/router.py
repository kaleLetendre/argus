"""Turn an utterance into an action: navigate, report status, or answer.

This is the text stand-in for the voice front end. When microphones land, the
speech-to-text result feeds straight into :func:`handle`; nothing below cares
whether the words were typed or spoken.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from argus.knowledge import answer_question
from argus.workspace import Session, WorkspaceRegistry

# "open project cressida", "switch to cressida", "go to project x", "open the x build"
_NAV_RE = re.compile(
    r"^\s*(?:argus[ ,]+)?(?:open|go to|switch to|load|enter)\s+(?:project\s+|the\s+)?(.+?)\s*$",
    re.IGNORECASE,
)
_STATUS_RE = re.compile(r"\b(where am i|what context|current context|status)\b", re.IGNORECASE)


@dataclass
class Reply:
    text: str
    kind: str  # "nav" | "status" | "answer" | "error"


def handle(utterance: str, registry: WorkspaceRegistry, session: Session) -> Reply:
    text = utterance.strip()
    if not text:
        return Reply("", "error")

    nav = _NAV_RE.match(text)
    if nav:
        target = nav.group(1)
        workspace = registry.resolve(target)
        if workspace is None:
            known = ", ".join(w.name for w in registry.all()) or "none"
            return Reply(f"No context matches '{target}'. Known: {known}.", "error")
        session.activate(workspace)
        return Reply(f"Opened {workspace.name}.", "nav")

    if _STATUS_RE.search(text):
        if session.active is None:
            return Reply("No context is active. Try 'open project <name>'.", "status")
        return Reply(f"You're in {session.active.name}.", "status")

    # Anything else is a question against the active context.
    if session.active is None:
        return Reply("No context is active. Open one first, e.g. 'open project cressida'.", "error")
    answer = answer_question(text, session.active, session)
    return Reply(answer.text, "answer")
