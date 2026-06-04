"""Hybrid question answering over the active context.

``answer_question`` is the single entry point the assistant calls once a
workspace is active. It:

1. figures out which entity the question is about (named directly, or the
   inferred focus for a type like "engine"),
2. tries to resolve a structured fact on that entity (exact answer), and
3. falls back to RAG over the workspace docs.

The returned :class:`Answer` always carries provenance so the spoken reply can
say where the number came from.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from jarvis.knowledge import rag
from jarvis.workspace.models import Entity, Fact, Workspace
from jarvis.workspace.session import Session

# Words that signal "the thing I'm currently focused on" rather than a named entity.
_FOCUS_HINTS = ("my", "current", "the", "this")

# Spoken type words mapped to entity ``type`` values in the graph.
_TYPE_WORDS = {
    "engine": "engine",
    "motor": "engine",
    "gearbox": "transmission",
    "transmission": "transmission",
    "part": "part",
    "tool": "tool",
}


@dataclass
class Answer:
    text: str
    found: bool = True
    entity: Entity | None = None
    fact: Fact | None = None
    source: str = ""
    passages: list[object] = field(default_factory=list)


def _detect_type(question: str) -> str | None:
    words = set(re.findall(r"[a-z]+", question.lower()))
    for word, entity_type in _TYPE_WORDS.items():
        if word in words:
            return entity_type
    return None


def _resolve_entity(
    question: str, workspace: Workspace, session: Session
) -> tuple[Entity | None, str]:
    """Pick the entity a question is about; second return value is a note."""
    # 1. A directly named entity wins ("the head gasket part number").
    named = workspace.graph.find_entity(question)
    if named is not None:
        session.note_mention(named)
        return named, "named directly"

    # 2. Otherwise infer focus from a type word ("my current engine").
    entity_type = _detect_type(question)
    if entity_type is not None:
        result = session.infer_focus(entity_type)
        if result.entity is not None:
            return result.entity, result.reason
        if result.ambiguous:
            names = ", ".join(e.name for e in result.ambiguous)
            return None, f"ambiguous {entity_type}: {names}"
        return None, result.reason

    return None, "no entity identified"


def answer_question(question: str, workspace: Workspace, session: Session) -> Answer:
    """Answer ``question`` using the active workspace's hybrid knowledge."""
    entity, note = _resolve_entity(question, workspace, session)

    # Stage 1: structured fact, fact-first.
    # If an entity is pinned, prefer its facts; otherwise scan every entity so a
    # spec question ("torque on the cam caps") still resolves without naming the
    # part. Any entity we answer from becomes the inferred focus.
    fact, fact_entity = None, entity
    if entity is not None:
        fact = entity.find_fact(question)
    if fact is None:
        best_score = 0.0
        for candidate in workspace.graph.entities.values():
            hit = candidate.find_fact(question)
            if hit is not None:
                score = candidate.match_score(question) + 1.0  # any fact hit beats no entity
                if score > best_score:
                    best_score, fact, fact_entity = score, hit, candidate
    if fact is not None and fact_entity is not None:
        session.note_mention(fact_entity)
        return Answer(
            text=f"{fact_entity.name}: {fact.key.replace('_', ' ')} is {fact.render()}.",
            entity=fact_entity,
            fact=fact,
            source=f"graph fact ({note})",
        )

    # Stage 2: RAG fallback over the docs.
    passages = rag.retrieve(workspace, question)
    if passages:
        top = passages[0]
        return Answer(
            text=top.text,
            entity=entity,
            source=f"docs:{top.source.name}",
            passages=passages,
        )

    # Nothing matched.
    hint = f" ({note})" if note else ""
    return Answer(
        text=f"I don't have that in the {workspace.name} context yet{hint}.",
        found=False,
        entity=entity,
        source="none",
    )
