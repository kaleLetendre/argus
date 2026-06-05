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
    """A safe, capitalised Neo4j label from a free-form type string.

    Neo4j labels cannot start with a digit, so a numeric-leading type is
    prefixed; an all-symbol type falls back to ``Thing``.
    """
    cleaned = re.sub(r"[^A-Za-z0-9]", "", entity_type).strip() or "Thing"
    if cleaned[0].isdigit():
        cleaned = "T" + cleaned
    return cleaned[:1].upper() + cleaned[1:]


def _rel_type(relation: str) -> str:
    """A safe relationship type from a free-form relation string."""
    return re.sub(r"[^A-Za-z0-9_]", "_", relation).upper() or "RELATED_TO"


def _lucene(text: str) -> str:
    """Reduce a spoken phrase to a safe Lucene OR-query of bare words."""
    words = re.findall(r"[a-z0-9]+", text.lower())
    return " ".join(words) if words else " "


def _uid(slug: str, entity_id: str) -> str:
    return f"{slug}:{entity_id}"


def _entity_search(name: str, entity_id: str, aliases: list[str]) -> str:
    """The denormalized full-text search string for an entity (one place)."""
    return " ".join([name, entity_id, *(aliases or [])])


def _proposal_signature(p: dict) -> str:
    """A content key identifying a proposal, so re-running enrichment doesn't
    stage the same entity/fact/relationship twice."""
    if p["kind"] == "entity":
        return f"entity:{p.get('id')}"
    if p["kind"] == "fact":
        return f"fact:{p.get('entity_id')}.{p.get('key')}"
    if p["kind"] == "relationship":
        return f"rel:{p.get('source')}-{p.get('relation')}-{p.get('target')}"
    return f"{p['kind']}:{p}"


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
        """Wipe ALL data. Destructive; used only by an explicit ``--reset``.
        Prefer :meth:`clear_workspace` for scoped resets."""
        with self._driver.session() as s:
            s.run("MATCH (n) DETACH DELETE n")

    def clear_workspace(self, slug: str) -> None:
        """Delete just one project's subgraph (entities, facts, docs, proposals),
        leaving every other workspace untouched."""
        with self._driver.session() as s:
            s.execute_write(
                lambda tx: (
                    tx.run(
                        "MATCH (e:Entity {workspace:$slug}) "
                        "OPTIONAL MATCH (e)-[:HAS_FACT]->(f:Fact) DETACH DELETE e, f",
                        slug=slug,
                    ),
                    tx.run("MATCH (d:Doc {workspace:$slug}) DETACH DELETE d", slug=slug),
                    tx.run("MATCH (p:Proposal {workspace:$slug}) DETACH DELETE p", slug=slug),
                    tx.run("MATCH (w:Workspace {slug:$slug}) DETACH DELETE w", slug=slug),
                )
            )

    # -- import (YAML workspace -> graph) -----------------------------------
    def import_workspace(self, ws: Workspace) -> None:
        """Seed/refresh one workspace. Runs as a single write transaction so a
        failure can't leave a half-loaded graph."""
        slug = ws.slug
        meta = {
            "slug": slug,
            "name": ws.name,
            "aliases": ws.aliases,
            "desc": ws.description,
            "search": " ".join([ws.name, slug, *ws.aliases]),
        }
        entities = [
            {
                "uid": _uid(slug, e.id),
                "id": e.id,
                "name": e.name,
                "type": e.type,
                "label": _label(e.type),
                "aliases": e.aliases,
                "search": _entity_search(e.name, e.id, e.aliases),
                "facts": [
                    {
                        "fuid": f"{_uid(slug, e.id)}#{f.key}",
                        "key": f.key,
                        "value": f.value,
                        "unit": f.unit,
                        "note": f.note,
                        "source": f.source,
                        "confidence": f.confidence,
                        "search": f.key.replace("_", " "),
                    }
                    for f in e.facts.values()
                ],
            }
            for e in ws.graph.entities.values()
        ]
        edges = [
            {
                "auid": _uid(slug, edge.source),
                "buid": _uid(slug, edge.target),
                "rel": _rel_type(edge.relation),
                "weight": edge.weight,
                "confidence": edge.confidence,
                "relation": edge.relation,
            }
            for edge in ws.graph.edges
        ]
        docs = [
            {
                "duid": f"{slug}:{p.name}",
                "path": str(p),
                "name": p.name,
                "text": Path(p).read_text(encoding="utf-8"),
            }
            for p in ws.doc_paths
        ]
        with self._driver.session() as s:
            s.execute_write(_import_tx, meta, entities, edges, docs)

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

    def search_facts(
        self, slug: str, query: str, limit: int = 12
    ) -> list[tuple[Entity, Fact, float]]:
        """Full-text over fact keys, re-ranked by the difflib fact scorer.

        Returns ``(entity, fact, score)`` sorted best-first, so callers pick the
        genuinely closest fact rather than whatever Lucene happened to order
        first. Critical for spec questions: a wrong torque number must not win on
        index order alone.
        """
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
            out: list[tuple[Entity, Fact, float]] = []
            seen: set[str] = set()
            for r in rows:
                if r["uid"] in seen:
                    continue
                seen.add(r["uid"])
                entity = self._load_entity(s, r["uid"])
                if entity:
                    hit = entity.best_fact(query)
                    if hit:
                        out.append((entity, hit[0], hit[1]))
        out.sort(key=lambda t: t[2], reverse=True)
        return out

    def entity_types(self, slug: str) -> list[str]:
        """Distinct entity ``type`` values present in a workspace (drives
        data-driven focus inference, so user-defined types resolve too)."""
        with self._driver.session() as s:
            rows = s.run(
                "MATCH (e:Entity {workspace:$slug}) RETURN DISTINCT e.type AS type",
                slug=slug,
            ).data()
        return [r["type"] for r in rows if r["type"]]

    def neighbors(self, slug: str, uid: str, relation: str | None = None) -> list[dict]:
        rel_clause = "" if relation is None else f":`{relation.upper()}`"
        with self._driver.session() as s:
            # ``n.workspace = $slug`` keeps traversal inside the project's own
            # graph: no edge ever crosses into another context.
            return s.run(
                f"MATCH (e:Entity {{uid:$uid}})-[r{rel_clause}]-(n:Entity) "
                "WHERE n.workspace = $slug "
                "RETURN n.name AS name, type(r) AS relation, "
                "coalesce(r.weight,1.0) AS weight, coalesce(r.confidence,1.0) AS confidence "
                "ORDER BY weight DESC",
                uid=uid,
                slug=slug,
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

    # -- enrichment support -------------------------------------------------
    def get_docs(self, slug: str) -> list[dict]:
        with self._driver.session() as s:
            return s.run(
                "MATCH (d:Doc {workspace:$slug}) RETURN d.name AS name, d.text AS text "
                "ORDER BY d.name",
                slug=slug,
            ).data()

    def graph_snapshot(self, slug: str) -> str:
        """A compact text view of the existing graph, to keep Claude from
        re-proposing things already present."""
        with self._driver.session() as s:
            ents = s.run(
                "MATCH (e:Entity {workspace:$slug}) "
                "OPTIONAL MATCH (e)-[:HAS_FACT]->(f:Fact) "
                "RETURN e.id AS id, e.type AS type, e.name AS name, "
                "collect(f.key) AS facts ORDER BY e.id",
                slug=slug,
            ).data()
            rels = s.run(
                "MATCH (a:Entity {workspace:$slug})-[r]->(b:Entity {workspace:$slug}) "
                "WHERE type(r) <> 'HAS_FACT' "
                "RETURN a.id AS source, type(r) AS rel, b.id AS target",
                slug=slug,
            ).data()
        lines = [
            f"- {e['name']} (id={e['id']}, type={e['type']}) facts: "
            f"{', '.join(e['facts']) or 'none'}"
            for e in ents
        ]
        for r in rels:
            lines.append(f"- ({r['source']})-[{r['rel']}]->({r['target']})")
        return "\n".join(lines)

    # -- proposals (staged enrichment, reviewed before applying) ------------
    def stage_proposals(self, slug: str, proposals: list[dict]) -> list[str]:
        """Stage proposals for review, skipping any that duplicate one already
        pending for this workspace (so repeated 'study the docs' doesn't pile up
        identical entries)."""
        import json
        import uuid

        with self._driver.session() as s:
            existing = {
                r["sig"]
                for r in s.run(
                    "MATCH (p:Proposal {workspace:$slug, status:'pending'}) "
                    "RETURN p.sig AS sig",
                    slug=slug,
                ).data()
            }
            ids: list[str] = []
            for p in proposals:
                sig = _proposal_signature(p)
                if sig in existing:
                    continue
                existing.add(sig)
                pid = uuid.uuid4().hex[:12]
                s.run(
                    "MERGE (p:Proposal {pid:$pid}) "
                    "SET p.workspace=$slug, p.kind=$kind, p.status='pending', p.sig=$sig, "
                    "p.summary=$summary, p.evidence=$evidence, p.doc=$doc, "
                    "p.confidence=$confidence, p.payload=$payload "
                    "WITH p MATCH (w:Workspace {slug:$slug}) MERGE (p)-[:PROPOSED_FOR]->(w)",
                    pid=pid,
                    slug=slug,
                    kind=p["kind"],
                    sig=sig,
                    summary=_summarize(p),
                    evidence=p.get("evidence", ""),
                    doc=p.get("doc", ""),
                    confidence=p.get("confidence", 0.5),
                    payload=json.dumps(p),
                )
                ids.append(pid)
        return ids

    def pending_signatures(self, slug: str) -> list[str]:
        """Human-readable summaries of pending proposals, for the enrichment
        prompt so Claude avoids re-proposing what's already queued."""
        return [p["summary"] for p in self.list_proposals(slug)]

    def list_proposals(self, slug: str, status: str = "pending") -> list[dict]:
        with self._driver.session() as s:
            return s.run(
                "MATCH (p:Proposal {workspace:$slug, status:$status}) "
                "RETURN p.pid AS pid, p.kind AS kind, p.summary AS summary, "
                "p.evidence AS evidence, p.doc AS doc, p.confidence AS confidence "
                "ORDER BY p.confidence DESC",
                slug=slug,
                status=status,
            ).data()

    def set_proposal_status(self, pid: str, status: str) -> bool:
        with self._driver.session() as s:
            rec = s.run(
                "MATCH (p:Proposal {pid:$pid}) SET p.status=$status RETURN p.pid AS pid",
                pid=pid,
                status=status,
            ).single()
        return rec is not None

    def approve_proposal(self, pid: str) -> dict:
        """Materialise a pending proposal into the graph and mark it approved,
        in one transaction (so it can't end up applied-but-still-pending).

        Returns a result dict with ``status``:
        ``applied`` | ``notfound`` | ``conflict`` (and ``slug``/``summary`` for
        the operator to confirm they approved the right thing). A ``conflict``
        means the proposal would overwrite an existing fact with equal/higher
        confidence and a different value; nothing is written.
        """
        import json

        def _txn(tx):
            rec = tx.run(
                "MATCH (p:Proposal {pid:$pid}) "
                "RETURN p.payload AS payload, p.workspace AS slug, "
                "p.status AS status, p.summary AS summary",
                pid=pid,
            ).single()
            if rec is None or rec["status"] != "pending":
                return {"status": "notfound"}
            p = json.loads(rec["payload"])
            slug, summary = rec["slug"], rec["summary"]
            conflict = _fact_conflict(tx, slug, p)
            if conflict is not None:
                return {"status": "conflict", "slug": slug, "summary": summary,
                        "existing": conflict}
            _apply_proposal(tx, slug, p)
            tx.run("MATCH (p:Proposal {pid:$pid}) SET p.status='approved'", pid=pid)
            return {"status": "applied", "slug": slug, "summary": summary}

        with self._driver.session() as s:
            return s.execute_write(_txn)


def _summarize(p: dict) -> str:
    """One-line human description of a proposal for the review screen."""
    if p["kind"] == "entity":
        return f"new {p.get('type','thing')} '{p.get('name')}'"
    if p["kind"] == "fact":
        unit = f" {p['unit']}" if p.get("unit") else ""
        return f"{p.get('entity_id')}.{p.get('key')} = {p.get('value')}{unit}"
    if p["kind"] == "relationship":
        return f"({p.get('source')})-[{p.get('relation')}]->({p.get('target')})"
    return p["kind"]


def _import_tx(tx, meta: dict, entities: list[dict], edges: list[dict], docs: list[dict]) -> None:
    """Apply a whole workspace import inside one write transaction."""
    slug = meta["slug"]
    tx.run(
        "MERGE (w:Workspace {slug:$slug}) "
        "SET w.name=$name, w.aliases=$aliases, w.description=$desc, w.search=$search",
        **meta,
    )
    for e in entities:
        tx.run(
            f"MERGE (n:Entity {{uid:$uid}}) "
            f"SET n:`{e['label']}`, n.id=$id, n.name=$name, n.type=$type, "
            f"n.aliases=$aliases, n.workspace=$slug, n.search=$search "
            f"WITH n MATCH (w:Workspace {{slug:$slug}}) MERGE (n)-[:IN_WORKSPACE]->(w)",
            uid=e["uid"], id=e["id"], name=e["name"], type=e["type"],
            aliases=e["aliases"], slug=slug, search=e["search"],
        )
        for f in e["facts"]:
            tx.run(
                "MATCH (n:Entity {uid:$uid}) MERGE (fct:Fact {uid:$fuid}) "
                "SET fct.key=$key, fct.value=$value, fct.unit=$unit, fct.note=$note, "
                "fct.source=$source, fct.confidence=$confidence, fct.search=$search "
                "MERGE (n)-[:HAS_FACT]->(fct)",
                uid=e["uid"], fuid=f["fuid"], key=f["key"], value=f["value"],
                unit=f["unit"], note=f["note"], source=f["source"],
                confidence=f["confidence"], search=f["search"],
            )
    for ed in edges:
        tx.run(
            f"MATCH (a:Entity {{uid:$auid}}), (b:Entity {{uid:$buid}}) "
            f"MERGE (a)-[r:`{ed['rel']}`]->(b) "
            f"SET r.weight=$weight, r.confidence=$confidence, r.relation=$relation",
            auid=ed["auid"], buid=ed["buid"], weight=ed["weight"],
            confidence=ed["confidence"], relation=ed["relation"],
        )
    for d in docs:
        tx.run(
            "MERGE (doc:Doc {uid:$duid}) "
            "SET doc.path=$path, doc.name=$name, doc.text=$text, doc.workspace=$slug "
            "WITH doc MATCH (w:Workspace {slug:$slug}) MERGE (doc)-[:IN_WORKSPACE]->(w)",
            duid=d["duid"], path=d["path"], name=d["name"], text=d["text"], slug=slug,
        )


def _fact_conflict(tx, slug: str, p: dict) -> dict | None:
    """If approving a fact proposal would clobber an existing fact that is at
    least as confident but has a *different* value, return the existing fact so
    the caller can refuse. Same-value re-approval and lower-confidence existing
    facts are not conflicts."""
    if p.get("kind") != "fact":
        return None
    fuid = f"{_uid(slug, p['entity_id'])}#{p['key']}"
    rec = tx.run(
        "MATCH (f:Fact {uid:$fuid}) "
        "RETURN f.value AS value, f.confidence AS confidence, f.source AS source",
        fuid=fuid,
    ).single()
    if rec is None:
        return None
    existing_conf = rec["confidence"] if rec["confidence"] is not None else 1.0
    proposed_conf = p.get("confidence", 0.5)
    if str(rec["value"]) != str(p.get("value")) and existing_conf >= proposed_conf:
        return {"value": rec["value"], "confidence": existing_conf, "source": rec["source"]}
    return None


def _apply_proposal(tx, slug: str, p: dict) -> None:
    """Write one approved proposal into the graph, tagged as machine-extracted.
    New entities created as a side effect are linked into the workspace; the
    workspace node is MATCHed (never MERGEd) so a stray duplicate can't appear."""
    source = f"claude-extraction:{p.get('doc')}" if p.get("doc") else "claude-extraction"
    kind = p["kind"]

    if kind == "entity":
        tx.run(
            f"MERGE (e:Entity {{uid:$uid}}) "
            f"SET e:`{_label(p.get('type','thing'))}`, e.id=$id, e.name=$name, e.type=$type, "
            f"e.aliases=$aliases, e.workspace=$slug, e.search=$search "
            f"WITH e MATCH (w:Workspace {{slug:$slug}}) MERGE (e)-[:IN_WORKSPACE]->(w)",
            uid=_uid(slug, p["id"]), id=p["id"], name=p["name"],
            type=p.get("type", "thing"), aliases=p.get("aliases") or [], slug=slug,
            search=_entity_search(p["name"], p["id"], p.get("aliases") or []),
        )

    elif kind == "fact":
        uid = _uid(slug, p["entity_id"])
        tx.run(
            "MERGE (e:Entity {uid:$uid}) "
            "ON CREATE SET e.id=$eid, e.name=$eid, e.type='thing', e.workspace=$slug, e.search=$eid "
            "WITH e MATCH (w:Workspace {slug:$slug}) MERGE (e)-[:IN_WORKSPACE]->(w) "
            "MERGE (f:Fact {uid:$fuid}) "
            "SET f.key=$key, f.value=$value, f.unit=$unit, f.note=$note, "
            "f.source=$source, f.confidence=$confidence, f.search=$search "
            "MERGE (e)-[:HAS_FACT]->(f)",
            uid=uid, eid=p["entity_id"], slug=slug, fuid=f"{uid}#{p['key']}",
            key=p["key"], value=p.get("value"), unit=p.get("unit"), note=p.get("note"),
            source=source, confidence=p.get("confidence", 0.5),
            search=p["key"].replace("_", " "),
        )

    elif kind == "relationship":
        rel = _rel_type(p["relation"])
        tx.run(
            f"MERGE (a:Entity {{uid:$auid}}) "
            f"ON CREATE SET a.id=$sid, a.name=$sid, a.type='thing', a.workspace=$slug, a.search=$sid "
            f"MERGE (b:Entity {{uid:$buid}}) "
            f"ON CREATE SET b.id=$tid, b.name=$tid, b.type='thing', b.workspace=$slug, b.search=$tid "
            f"WITH a, b MATCH (w:Workspace {{slug:$slug}}) "
            f"MERGE (a)-[:IN_WORKSPACE]->(w) MERGE (b)-[:IN_WORKSPACE]->(w) "
            f"MERGE (a)-[r:`{rel}`]->(b) "
            f"SET r.weight=$weight, r.confidence=$confidence, r.relation=$relation, r.source=$source",
            auid=_uid(slug, p["source"]), buid=_uid(slug, p["target"]),
            sid=p["source"], tid=p["target"], slug=slug,
            weight=p.get("weight", 1.0), confidence=p.get("confidence", 0.5),
            relation=p["relation"], source=source,
        )


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
        uid=node.get("uid"),
        workspace=node.get("workspace"),
    )
