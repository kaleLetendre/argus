"""Hybrid question answering over the active context (backed by Neo4j).

``answer_question`` is the single entry point the assistant calls once a
workspace is active. It:

1. figures out which entity the question is about (named directly via the
   entity full-text index, or the inferred focus for a type like "engine"),
2. tries to resolve a structured fact on that entity, and if none matches scans
   the workspace's facts via the fact full-text index (exact answers), and
3. falls back to RAG over the workspace docs.

The returned :class:`Answer` carries provenance so the spoken reply can say
where the number came from.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from argus.workspace.models import Entity, Fact
from argus.workspace.session import Session

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


def _best_paragraph(text: str, question: str) -> str:
    """Pick the most relevant paragraph from a doc the index already matched."""
    q = set(re.findall(r"[a-z0-9]+", question.lower()))
    best, best_score = text.strip(), 0.0
    for para in re.split(r"\n\s*\n", text):
        words = set(re.findall(r"[a-z0-9]+", para.lower()))
        score = len(q & words) / len(q) if q else 0.0
        if score > best_score:
            best, best_score = para.strip(), score
    return best


def answer_question(question: str, store, session: Session) -> Answer:
    """Answer ``question`` using the active workspace's hybrid knowledge."""
    slug = session.active.slug
    ws_name = session.active.name

    # 1. Resolve the entity the question is about.
    entity = store.find_entity(slug, question)
    note = "named directly"
    if entity is not None:
        session.note_mention(entity)
    else:
        entity_type = _detect_type(question)
        if entity_type is not None:
            result = session.infer_focus(entity_type, store)
            entity, note = result.entity, result.reason
            if entity is None and result.ambiguous:
                names = ", ".join(e.name for e in result.ambiguous)
                return Answer(
                    text=f"Which {entity_type}? I know of: {names}.",
                    found=False,
                    source="disambiguation",
                )

    # 2. Fact-first. Prefer the resolved entity's facts; else scan workspace facts.
    fact: Fact | None = None
    fact_entity = entity
    if entity is not None:
        fact = entity.find_fact(question)
    if fact is None:
        for cand_entity, cand_fact in store.search_facts(slug, question):
            fact, fact_entity = cand_fact, cand_entity
            break
    if fact is not None and fact_entity is not None:
        session.note_mention(fact_entity)
        conf = "" if fact.confidence >= 1.0 else f" [confidence {fact.confidence:.0%}]"
        return Answer(
            text=f"{fact_entity.name}: {fact.key.replace('_', ' ')} is {fact.render()}.{conf}",
            entity=fact_entity,
            fact=fact,
            source=f"graph fact ({note})",
        )

    # 3. RAG fallback over docs.
    docs = store.search_docs(slug, question)
    if docs:
        top = docs[0]
        return Answer(
            text=_best_paragraph(top["text"], question),
            entity=entity,
            source=f"docs:{top['name']}",
            passages=docs,
        )

    hint = f" ({note})" if note and note != "named directly" else ""
    return Answer(
        text=f"I don't have that in the {ws_name} context yet{hint}.",
        found=False,
        entity=entity,
        source="none",
    )
