"""Core data model for the workspace system.

A ``Workspace`` is one project context (a folder on disk). Its knowledge lives
as an entity ``Graph``: ``Entity`` nodes carry structured ``Fact`` values, and
``Edge`` relationships connect them. Free-form prose lives in markdown docs,
referenced by path and consumed by the RAG layer.

Everything here is intentionally plain (dataclasses + dicts) so the on-disk
YAML maps cleanly onto Python and the whole graph stays inspectable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path


def _normalize(text: str) -> str:
    """Lowercase and collapse to bare words for forgiving name matching."""
    return re.sub(r"[^a-z0-9 ]+", " ", text.lower()).strip()


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, _normalize(a), _normalize(b)).ratio()


def _contains_words(haystack_n: str, needle_n: str) -> bool:
    """True if normalized ``needle`` appears as a whole-word run in ``haystack``
    (or vice-versa). Avoids substring false positives like "hg" inside "weight"."""
    a, b = f" {haystack_n} ", f" {needle_n} "
    return b in a or a in b


@dataclass
class Fact:
    """A single structured fact attached to an entity.

    ``value`` is the raw datum (number or string), ``unit`` is optional, and
    ``note``/``source`` capture provenance so an answer can cite where the spec
    came from. Stored in YAML as either a scalar or a small mapping.
    """

    key: str
    value: object
    unit: str | None = None
    note: str | None = None
    source: str | None = None
    # 1.0 = stated by the user / a manual; lower for auto-extracted (voice, vision).
    confidence: float = 1.0

    def render(self) -> str:
        text = f"{self.value}" if self.unit is None else f"{self.value} {self.unit}"
        if self.note:
            text += f" ({self.note})"
        return text

    @classmethod
    def parse(cls, key: str, raw: object) -> "Fact":
        if isinstance(raw, dict):
            return cls(
                key=key,
                value=raw.get("value"),
                unit=raw.get("unit"),
                note=raw.get("note"),
                source=raw.get("source"),
                confidence=float(raw.get("confidence", 1.0)),
            )
        return cls(key=key, value=raw)


@dataclass
class Entity:
    """A node in the project graph (an engine, a part, a tool, a workbench)."""

    id: str
    type: str
    name: str
    aliases: list[str] = field(default_factory=list)
    facts: dict[str, Fact] = field(default_factory=dict)
    docs: list[str] = field(default_factory=list)
    # Stable graph identity, preserved from the store so two same-`id` entities
    # in different projects never collapse together in memory.
    uid: str | None = None
    workspace: str | None = None

    def names(self) -> list[str]:
        return [self.name, self.id, *self.aliases]

    def match_score(self, mention: str) -> float:
        """How strongly a spoken mention refers to this entity (0..1)."""
        mention_n = _normalize(mention)
        best = 0.0
        for candidate in self.names():
            cand_n = _normalize(candidate)
            if not cand_n:
                continue
            # Whole-token containment only, and never for tiny aliases ("hg"),
            # so a 2-char alias can't greedily match unrelated questions.
            if len(cand_n) >= 3 and _contains_words(mention_n, cand_n):
                best = max(best, 0.9)
            best = max(best, _similarity(mention, candidate))
        return best

    def best_fact(self, query: str, threshold: float = 0.45) -> tuple[Fact, float] | None:
        """Best fact for a spoken phrase, with its score, or ``None``."""
        query_words = set(_normalize(query).split())
        best: tuple[float, Fact] | None = None
        for key, fact in self.facts.items():
            key_words = set(_normalize(key.replace("_", " ")).split())
            if not key_words:
                continue
            overlap = len(key_words & query_words) / len(key_words)
            fuzzy = _similarity(query, key.replace("_", " "))
            score = max(overlap, fuzzy)
            if score >= threshold and (best is None or score > best[0]):
                best = (score, fact)
        return (best[1], best[0]) if best else None

    def find_fact(self, query: str, threshold: float = 0.45) -> Fact | None:
        """Resolve a spoken phrase ("cam cap torque") to a stored fact key."""
        hit = self.best_fact(query, threshold)
        return hit[0] if hit is not None else None


@dataclass
class Edge:
    """A directed relationship between two entities (``source --relation--> target``).

    ``weight`` is the strength of the association (used to rank/traverse), and
    ``confidence`` is how sure we are the relationship holds. Both default to
    1.0; auto-populated edges (voice/vision) will carry lower values. These are
    plain edge properties, the explainable, symbolic counterpart to the learned
    embedding layer that will sit over the graph later.
    """

    source: str
    relation: str
    target: str
    weight: float = 1.0
    confidence: float = 1.0

    @classmethod
    def parse(cls, raw: dict) -> "Edge":
        return cls(
            source=raw["source"],
            relation=raw["relation"],
            target=raw["target"],
            weight=float(raw.get("weight", 1.0)),
            confidence=float(raw.get("confidence", 1.0)),
        )


@dataclass
class Graph:
    """The entity graph for one project: nodes plus the edges between them."""

    entities: dict[str, Entity] = field(default_factory=dict)
    edges: list[Edge] = field(default_factory=list)

    def get(self, entity_id: str) -> Entity | None:
        return self.entities.get(entity_id)

    def by_type(self, entity_type: str) -> list[Entity]:
        return [e for e in self.entities.values() if e.type == entity_type]

    def neighbors(self, entity_id: str, relation: str | None = None) -> list[Entity]:
        out: list[Entity] = []
        for edge in self.edges:
            if edge.source == entity_id and (relation is None or edge.relation == relation):
                target = self.get(edge.target)
                if target:
                    out.append(target)
        return out

    def find_entity(self, mention: str, threshold: float = 0.6) -> Entity | None:
        """Best entity referenced by a spoken phrase, or ``None`` if unclear."""
        best: tuple[float, Entity] | None = None
        for entity in self.entities.values():
            score = entity.match_score(mention)
            if score >= threshold and (best is None or score > best[0]):
                best = (score, entity)
        return best[1] if best else None


@dataclass
class Workspace:
    """One project context: identity, its entity graph, and its doc corpus."""

    slug: str
    name: str
    path: Path
    aliases: list[str] = field(default_factory=list)
    description: str = ""
    graph: Graph = field(default_factory=Graph)
    doc_paths: list[Path] = field(default_factory=list)

    def names(self) -> list[str]:
        return [self.name, self.slug, *self.aliases]

    def match_score(self, query: str) -> float:
        """How well a spoken phrase ("project cressida") names this workspace."""
        query_n = _normalize(query)
        best = 0.0
        for candidate in self.names():
            cand_n = _normalize(candidate)
            if not cand_n:
                continue
            if cand_n in query_n or query_n in cand_n:
                best = max(best, 0.95)
            best = max(best, _similarity(query, candidate))
        return best
