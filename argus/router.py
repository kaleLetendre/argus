"""Turn an utterance into an action: navigate, report status, or answer.

This is the text stand-in for the voice front end. When microphones land, the
speech-to-text result feeds straight into :func:`handle`; nothing below cares
whether the words were typed or spoken.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from argus.knowledge import answer_question
from argus.workspace import Session

# "open project cressida", "switch to cressida", "go to project x", "open the x build"
_NAV_RE = re.compile(
    r"^\s*(?:argus[ ,]+)?(?:open|go to|switch to|load|enter)\s+(?:project\s+|the\s+)?(.+?)\s*$",
    re.IGNORECASE,
)
_STATUS_RE = re.compile(r"\b(where am i|what context|current context|status)\b", re.IGNORECASE)
# Explicit, anchored command so a stray keyword inside a *question* can't kick
# off a long job: "study the docs", "learn from the notes", "study this project".
# NOTE: enrichment still runs synchronously here and blocks the turn. Before real
# voice input lands this must move to a backgrounded, acknowledged job (the loose
# trigger + multi-second blocking call is a poor seam for spoken interaction).
_STUDY_RE = re.compile(
    r"^\s*(?:argus[ ,]+)?(?:study|learn from|ruminate over|read)\s+"
    r"(?:the\s+|this\s+|my\s+)?(?:docs|documents|notes|project|workspace)\b",
    re.IGNORECASE,
)


@dataclass
class Reply:
    text: str
    kind: str  # "nav" | "status" | "answer" | "error"


def handle(utterance: str, store, session: Session) -> Reply:
    text = utterance.strip()
    if not text:
        return Reply("", "error")

    nav = _NAV_RE.match(text)
    if nav:
        target = nav.group(1)
        workspace = store.resolve_workspace(target)
        if workspace is None:
            known = ", ".join(w.name for w in store.list_workspaces()) or "none"
            return Reply(f"No context matches '{target}'. Known: {known}.", "error")
        session.activate(workspace)
        return Reply(f"Opened {workspace.name}.", "nav")

    if _STATUS_RE.search(text):
        if session.active is None:
            return Reply("No context is active. Try 'open project <name>'.", "status")
        return Reply(f"You're in {session.active.name}.", "status")

    if _STUDY_RE.search(text):
        if session.active is None:
            return Reply("Open a context first, then I can study its docs.", "error")
        # Imported lazily: enrichment pulls in the Claude Agent SDK.
        from argus.enrich import enrich_workspace

        result = enrich_workspace(session.active.slug, store)
        if result["staged"] == 0:
            return Reply(f"I studied the docs but found nothing new to add ({result.get('reason','')}).", "answer")
        return Reply(
            f"I studied the docs and staged {result['staged']} proposal(s) for your review. "
            f"Run: python -m argus.enrich review {session.active.slug}",
            "answer",
        )

    # Anything else is a question against the active context.
    if session.active is None:
        return Reply("No context is active. Open one first, e.g. 'open project cressida'.", "error")
    answer = answer_question(text, store, session)
    return Reply(answer.text, "answer")
