"""Neo4j is the canonical store for the knowledge network.

Graph model
-----------
* ``(:Workspace {slug, name, aliases, description})`` -- one context.
* ``(:Entity {uid, id, name, type, aliases})`` with a second label equal to the
  capitalised ``type`` (``:Engine``, ``:Part``) so the Neo4j browser colours the
  graph by kind. ``uid = "<slug>:<id>"`` keeps ids unique across workspaces
  (Community edition is single-database, so workspaces are partitioned by node,
  not by database).
* ``(:Entity)-[:HAS_FACT]->(:Fact {key, value, unit, note, source, confidence})``
  -- facts are first-class nodes so provenance is queryable and visible.
* ``(:Entity)-[:<RELATION> {weight, confidence}]->(:Entity)`` -- your edges.
  ``weight`` is association strength, ``confidence`` is how sure we are; both
  default to 1.0 and drop for auto-populated edges (voice/vision).
* ``(:Doc {uid, path, name, text})`` -- prose knowledge for RAG.

Fuzzy lookups (spoken names, fact phrases, doc search) go through Lucene
full-text indexes so they stay fast as the graph grows; the small final ranking
reuses the Python scorers on the model objects.
"""

from __future__ import annotations

import re
from pathlib import Path

from neo4j import GraphDatabase

from argus.config import Neo4jConfig
from argus.workspace.models import Entity, Fact, Workspace

# Full-text index names.
IDX_WORKSPACE = "workspace_search"
IDX_ENTITY = "entity_search"
IDX_FACT = "fact_search"
IDX_DOC = "doc_search"


def _label(entity_type: str) -> str:
    """A safe, capitalised Neo4j label from a free-form type string."""
    cleaned = re.sub(r"[^A-Za-z0-9]", "", entity_type).strip() or "Thing"
    return cleaned[:1].upper() + cleaned[1:]


def _lucene(text: str) -> str:
    """Reduce a spoken phrase to a safe Lucene OR-query of bare words."""
    words = re.findall(r"[a-z0-9]+", text.lower())
    return " ".join(words) if words else " "


def _uid(slug: str, entity_id: str) -> str:
    return f"{slug}:{entity_id}"


class Neo4jStore:
    def __init__(self, config: Neo4jConfig):
        self._driver = GraphDatabase.driver(config.uri, auth=(config.user, config.password))

    def close(self) -> None:
        self._driver.close()

    def __enter__(self) -> "Neo4jStore":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def verify(self) -> None:
        """Raise if the database is unreachable / auth is wrong."""
        self._driver.verify_connectivity()

    # -- schema -------------------------------------------------------------
    def setup_schema(self) -> None:
        stmts = [
            "CREATE CONSTRAINT workspace_slug IF NOT EXISTS "
            "FOR (w:Workspace) REQUIRE w.slug IS UNIQUE",
            "CREATE CONSTRAINT entity_uid IF NOT EXISTS "
            "FOR (e:Entity) REQUIRE e.uid IS UNIQUE",
            "CREATE CONSTRAINT fact_uid IF NOT EXISTS "
            "FOR (f:Fact) REQUIRE f.uid IS UNIQUE",
            "CREATE CONSTRAINT doc_uid IF NOT EXISTS "
            "FOR (d:Doc) REQUIRE d.uid IS UNIQUE",
            f"CREATE FULLTEXT INDEX {IDX_WORKSPACE} IF NOT EXISTS "
            "FOR (w:Workspace) ON EACH [w.search]",
            f"CREATE FULLTEXT INDEX {IDX_ENTITY} IF NOT EXISTS "
            "FOR (e:Entity) ON EACH [e.search]",
            f"CREATE FULLTEXT INDEX {IDX_FACT} IF NOT EXISTS "
            "FOR (f:Fact) ON EACH [f.search]",
            f"CREATE FULLTEXT INDEX {IDX_DOC} IF NOT EXISTS "
            "FOR (d:Doc) ON EACH [d.text]",
        ]
        with self._driver.session() as s:
            for stmt in stmts:
                s.run(stmt)

    def clear(self) -> None:
        """Wipe all data (used by re-import and tests). Schema is kept."""
        with self._driver.session() as s:
            s.run("MATCH (n) DETACH DELETE n")

    # -- import (YAML workspace -> graph) -----------------------------------
    def import_workspace(self, ws: Workspace) -> None:
        slug = ws.slug
        with self._driver.session() as s:
            s.run(
                "MERGE (w:Workspace {slug:$slug}) "
                "SET w.name=$name, w.aliases=$aliases, w.description=$desc, w.search=$search",
                slug=slug,
                name=ws.name,
                aliases=ws.aliases,
                desc=ws.description,
                search=" ".join([ws.name, slug, *ws.aliases]),
            )

            for entity in ws.graph.entities.values():
                uid = _uid(slug, entity.id)
                s.run(
                    f"MERGE (e:Entity {{uid:$uid}}) "
                    f"SET e:`{_label(entity.type)}`, e.id=$id, e.name=$name, e.type=$type, "
                    f"e.aliases=$aliases, e.workspace=$slug, e.search=$search "
                    f"WITH e MATCH (w:Workspace {{slug:$slug}}) MERGE (e)-[:IN_WORKSPACE]->(w)",
                    uid=uid,
                    id=entity.id,
                    name=entity.name,
                    type=entity.type,
                    aliases=entity.aliases,
                    slug=slug,
                    search=" ".join([entity.name, entity.id, *entity.aliases]),
                )
                for fact in entity.facts.values():
                    fuid = f"{uid}#{fact.key}"
                    s.run(
                        "MERGE (f:Fact {uid:$fuid}) "
                        "SET f.key=$key, f.value=$value, f.unit=$unit, f.note=$note, "
                        "f.source=$source, f.confidence=$confidence, f.search=$search "
                        "WITH f MATCH (e:Entity {uid:$uid}) MERGE (e)-[:HAS_FACT]->(f)",
                        fuid=fuid,
                        key=fact.key,
                        value=fact.value,
                        unit=fact.unit,
                        note=fact.note,
                        source=fact.source,
                        confidence=fact.confidence,
                        search=fact.key.replace("_", " "),
                        uid=uid,
                    )

            for edge in ws.graph.edges:
                rel = re.sub(r"[^A-Za-z0-9_]", "_", edge.relation).upper() or "RELATED_TO"
                s.run(
                    f"MATCH (a:Entity {{uid:$auid}}), (b:Entity {{uid:$buid}}) "
                    f"MERGE (a)-[r:`{rel}`]->(b) "
                    f"SET r.weight=$weight, r.confidence=$confidence, r.relation=$relation",
                    auid=_uid(slug, edge.source),
                    buid=_uid(slug, edge.target),
                    weight=edge.weight,
                    confidence=edge.confidence,
                    relation=edge.relation,
                )

            for doc_path in ws.doc_paths:
                duid = f"{slug}:{doc_path.name}"
                s.run(
                    "MERGE (d:Doc {uid:$duid}) "
                    "SET d.path=$path, d.name=$name, d.text=$text, d.workspace=$slug "
                    "WITH d MATCH (w:Workspace {slug:$slug}) MERGE (d)-[:IN_WORKSPACE]->(w)",
                    duid=duid,
                    path=str(doc_path),
                    name=doc_path.name,
                    text=Path(doc_path).read_text(encoding="utf-8"),
                    slug=slug,
                )

    # -- queries ------------------------------------------------------------
    def list_workspaces(self) -> list[Workspace]:
        with self._driver.session() as s:
            rows = s.run(
                "MATCH (w:Workspace) RETURN w.slug AS slug, w.name AS name, "
                "w.aliases AS aliases, w.description AS description"
            ).data()
        return [
            Workspace(
                slug=r["slug"],
                name=r["name"],
                path=Path("."),
                aliases=r.get("aliases") or [],
                description=r.get("description") or "",
            )
            for r in rows
        ]

    def resolve_workspace(self, query: str, threshold: float = 0.5) -> Workspace | None:
        best: tuple[float, Workspace] | None = None
        for ws in self.list_workspaces():
            score = ws.match_score(query)
            if score >= threshold and (best is None or score > best[0]):
                best = (score, ws)
        return best[1] if best else None

    def _load_entity(self, session, uid: str) -> Entity | None:
        rec = session.run(
            "MATCH (e:Entity {uid:$uid}) "
            "OPTIONAL MATCH (e)-[:HAS_FACT]->(f:Fact) "
            "RETURN e AS e, collect(f) AS facts",
            uid=uid,
        ).single()
        if rec is None:
            return None
        return _entity_from(rec["e"], rec["facts"])

    def find_entity(self, slug: str, mention: str, limit: int = 8) -> Entity | None:
        with self._driver.session() as s:
            rows = s.run(
                f"CALL db.index.fulltext.queryNodes('{IDX_ENTITY}', $q) "
                "YIELD node, score WHERE node.workspace = $slug "
                "RETURN node.uid AS uid LIMIT $limit",
                q=_lucene(mention),
                slug=slug,
                limit=limit,
            ).data()
            candidates = [self._load_entity(s, r["uid"]) for r in rows]
        candidates = [c for c in candidates if c]
        best: tuple[float, Entity] | None = None
        for entity in candidates:
            score = entity.match_score(mention)
            if score >= 0.6 and (best is None or score > best[0]):
                best = (score, entity)
        return best[1] if best else None

    def by_type(self, slug: str, entity_type: str) -> list[Entity]:
        with self._driver.session() as s:
            rows = s.run(
                "MATCH (e:Entity {workspace:$slug, type:$type}) RETURN e.uid AS uid",
                slug=slug,
                type=entity_type,
            ).data()
            return [e for e in (self._load_entity(s, r["uid"]) for r in rows) if e]

    def search_facts(self, slug: str, query: str, limit: int = 12) -> list[tuple[Entity, Fact]]:
        """Full-text over fact keys; returns (entity, fact) pairs to re-rank."""
        with self._driver.session() as s:
            rows = s.run(
                f"CALL db.index.fulltext.queryNodes('{IDX_FACT}', $q) "
                "YIELD node, score "
                "MATCH (e:Entity {workspace:$slug})-[:HAS_FACT]->(node) "
                "RETURN e.uid AS uid LIMIT $limit",
                q=_lucene(query),
                slug=slug,
                limit=limit,
            ).data()
            out: list[tuple[Entity, Fact]] = []
            seen: set[str] = set()
            for r in rows:
                if r["uid"] in seen:
                    continue
                seen.add(r["uid"])
                entity = self._load_entity(s, r["uid"])
                if entity:
                    fact = entity.find_fact(query)
                    if fact:
                        out.append((entity, fact))
            return out

    def neighbors(self, slug: str, uid: str, relation: str | None = None) -> list[dict]:
        rel_clause = "" if relation is None else f":`{relation.upper()}`"
        with self._driver.session() as s:
            return s.run(
                f"MATCH (e:Entity {{uid:$uid}})-[r{rel_clause}]-(n:Entity) "
                "RETURN n.name AS name, type(r) AS relation, "
                "coalesce(r.weight,1.0) AS weight, coalesce(r.confidence,1.0) AS confidence "
                "ORDER BY weight DESC",
                uid=uid,
            ).data()

    def search_docs(self, slug: str, query: str, top_k: int = 3) -> list[dict]:
        with self._driver.session() as s:
            return s.run(
                f"CALL db.index.fulltext.queryNodes('{IDX_DOC}', $q) "
                "YIELD node, score WHERE node.workspace = $slug "
                "RETURN node.name AS name, node.text AS text, score ORDER BY score DESC "
                "LIMIT $top_k",
                q=_lucene(query),
                slug=slug,
                top_k=top_k,
            ).data()


def _entity_from(node, fact_nodes) -> Entity:
    facts = {}
    for f in fact_nodes:
        if f is None:
            continue
        facts[f["key"]] = Fact(
            key=f["key"],
            value=f.get("value"),
            unit=f.get("unit"),
            note=f.get("note"),
            source=f.get("source"),
            confidence=f.get("confidence", 1.0),
        )
    return Entity(
        id=node["id"],
        type=node.get("type", "thing"),
        name=node["name"],
        aliases=node.get("aliases") or [],
        facts=facts,
    )
