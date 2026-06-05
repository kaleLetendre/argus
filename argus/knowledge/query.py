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

# Synonyms that map a spoken word onto an entity ``type`` value. These augment
# the workspace's *actual* types (queried at runtime), so a project with a
# user-defined type like "vehicle" or "fixture" resolves focus without a code
# edit, while common synonyms ("motor" -> engine) still work.
_TYPE_SYNONYMS = {
    "motor": "engine",
    "gearbox": "transmission",
}

# When two candidate facts score within this margin, ask rather than guess.
_FACT_TIE_MARGIN = 0.12
# Below this score we don't trust a bare fact-index hit enough to answer.
_FACT_MIN_SCORE = 0.5


@dataclass
class Answer:
    text: str
    found: bool = True
    entity: Entity | None = None
    fact: Fact | None = None
    source: str = ""
    passages: list[object] = field(default_factory=list)


def _detect_type(question: str, slug: str, store) -> str | None:
    """Find which entity *type* a question is about, using the workspace's own
    types plus a small synonym table. Data-driven so new types just work."""
    words = set(re.findall(r"[a-z]+", question.lower()))
    for entity_type in store.entity_types(slug):
        if entity_type and entity_type.lower() in words:
            return entity_type
    for word, entity_type in _TYPE_SYNONYMS.items():
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
        entity_type = _detect_type(question, slug, store)
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

    # 2. Fact-first. Prefer the resolved entity's facts; else scan workspace
    #    facts, but pick the BEST-scoring one (not whatever the index ordered
    #    first), and refuse to guess between near-ties.
    fact: Fact | None = None
    fact_entity = entity
    if entity is not None:
        fact = entity.find_fact(question)
    if fact is None:
        ranked = store.search_facts(slug, question)  # (entity, fact, score), best first
        ranked = [r for r in ranked if r[2] >= _FACT_MIN_SCORE]
        if ranked:
            top = ranked[0]
            # If a clearly-different runner-up is within the tie margin, ask.
            for other in ranked[1:]:
                if other[0].id != top[0].id and (top[2] - other[2]) <= _FACT_TIE_MARGIN:
                    where = f"{top[0].name} or {other[0].name}"
                    return Answer(
                        text=f"Which one, {where}? Name the part and I'll give the exact spec.",
                        found=False,
                        source="disambiguation",
                    )
                break
            fact_entity, fact = top[0], top[1]
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
